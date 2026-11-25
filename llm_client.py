"""Shared text-only client for the storyteller and judge."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    RequestTimeoutError,
)

from config import (
    ANTHROPIC_BASE_URL,
    DEFAULT_MAX_OUTPUT_TOKENS,
    MAX_RETRIES,
    MAX_RETRY_WAIT_SECONDS,
    MODEL_ID,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL_ID,
    REQUEST_TIMEOUT_SECONDS,
    get_anthropic_api_key,
    get_llm_provider,
    get_openrouter_api_key,
)

if TYPE_CHECKING:
    from anthropic._models import FinalRequestOptions
    from httpx2 import Headers

_API_ERRORS = (
    ((AuthenticationError, PermissionDeniedError), "Anthropic rejected the credentials or access."),
    (RateLimitError, "Anthropic's rate limit was reached."),
    ((APITimeoutError, RequestTimeoutError), "The Anthropic request timed out."),
    (APIConnectionError, "Could not connect to Anthropic."),
    (InternalServerError, "Anthropic returned a server error."),
    (NotFoundError, "The required Anthropic model is unavailable."),
)


@dataclass
class ModelCallCounter:
    """Count SDK calls initiated by the application within one scope."""

    count: int = 0
    limit: int | None = None


_active_call_counters: ContextVar[tuple[ModelCallCounter, ...]] = ContextVar(
    "active_model_call_counters", default=()
)


@contextmanager
def track_model_calls(*, limit: int | None = None) -> Iterator[ModelCallCounter]:
    """Measure logical calls, including failed requests and judge corrections."""
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError("A logical call limit must be a nonnegative integer.")
    counter = ModelCallCounter(limit=limit)
    token = _active_call_counters.set((*_active_call_counters.get(), counter))
    try:
        yield counter
    finally:
        _active_call_counters.reset(token)


class LLMClientError(RuntimeError):
    """A client failure with a message safe to display."""


class ModelCallBudgetExceeded(RuntimeError):
    """The logical call limit was reached before a request was sent."""


class WorkflowDeadlineExceeded(RuntimeError):
    """The workflow no longer has time for a model call or its result."""


_active_deadline: ContextVar[float | None] = ContextVar("active_deadline", default=None)


@contextmanager
def workflow_deadline(deadline: float) -> Iterator[None]:
    """Share a monotonic deadline across all model calls for one story."""
    outer = _active_deadline.get()
    token = _active_deadline.set(deadline if outer is None else min(outer, deadline))
    try:
        yield
    finally:
        _active_deadline.reset(token)


def check_workflow_deadline() -> float | None:
    """Return remaining workflow seconds, or raise once time has elapsed."""
    deadline = _active_deadline.get()
    if deadline is None:
        return None
    remaining = deadline - perf_counter()
    if remaining <= 0:
        raise WorkflowDeadlineExceeded("The story workflow ran out of time.")
    return remaining


class _BoundedAnthropic(Anthropic):
    """Apply time limits at the pinned SDK's per-attempt and backoff hooks."""

    def _prepare_options(self, options: FinalRequestOptions) -> FinalRequestOptions:
        remaining = check_workflow_deadline()
        if remaining is not None:
            # Application clients configure a numeric timeout. This caps each HTTP phase.
            options.timeout = min(REQUEST_TIMEOUT_SECONDS, remaining)
        return super()._prepare_options(options)

    def _calculate_retry_timeout(
        self, remaining_retries: int, options: FinalRequestOptions,
        response_headers: Headers | None = None,
    ) -> float:
        delay = min(
            super()._calculate_retry_timeout(remaining_retries, options, response_headers),
            MAX_RETRY_WAIT_SECONDS,
        )
        remaining = check_workflow_deadline()
        if remaining is not None and delay >= remaining:
            raise WorkflowDeadlineExceeded("The story workflow has no time for another retry.")
        return delay


class LLMClient:
    """Make synchronous, single-turn requests through a reusable Anthropic client."""

    def __init__(self, client: Anthropic | None = None) -> None:
        """Use an injected SDK client or configure one from local credentials."""
        self._model_id = MODEL_ID
        if client is None:
            try:
                provider = get_llm_provider()
                if provider == "openrouter":
                    api_key = get_openrouter_api_key()
                elif provider == "anthropic":
                    api_key = get_anthropic_api_key()
                else:
                    raise LLMClientError("Set LLM_PROVIDER to anthropic or openrouter.")
            except (OSError, UnicodeError):
                raise LLMClientError("Could not read the local .env file.") from None
            if provider == "openrouter":
                if not api_key:
                    raise LLMClientError("Set OPENROUTER_API_KEY in the environment or .env.")
                self._model_id = OPENROUTER_MODEL_ID
                client = _BoundedAnthropic(
                    auth_token=api_key,
                    base_url=OPENROUTER_BASE_URL,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    max_retries=MAX_RETRIES,
                )
            else:
                if not api_key:
                    raise LLMClientError("Set ANTHROPIC_API_KEY in the environment or .env.")
                client = _BoundedAnthropic(
                    api_key=api_key,
                    base_url=ANTHROPIC_BASE_URL,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    max_retries=MAX_RETRIES,
                )
        self._client = client

    @property
    def model_id(self) -> str:
        """Return the configured request model ID for this connection."""
        return self._model_id

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_message: str,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        json_schema: dict[str, object] | None = None,
    ) -> str:
        """Return complete response text, optionally constrained to a JSON schema."""
        if not system_prompt.strip() or not user_message.strip():
            raise ValueError("System prompt and user message must be non-empty.")
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer.")

        check_workflow_deadline()
        counters = _active_call_counters.get()
        if any(counter.limit is not None and counter.count >= counter.limit for counter in counters):
            raise ModelCallBudgetExceeded("The logical model call budget was exhausted.")
        for counter in counters:
            counter.count += 1
        try:
            response = self._client.messages.create(
                model=self.model_id,
                max_tokens=max_output_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                **(
                    {"output_config": {"format": {"type": "json_schema", "schema": json_schema}}}
                    if json_schema is not None
                    else {}
                ),
            )
        except APIError as error:
            try:
                check_workflow_deadline()
            except WorkflowDeadlineExceeded as deadline_error:
                raise deadline_error from None
            message = next(
                (message for kind, message in _API_ERRORS if isinstance(error, kind)),
                "The Anthropic request failed.",
            )
            raise LLMClientError(message) from None

        check_workflow_deadline()
        if response.stop_reason in {"max_tokens", "model_context_window_exceeded"}:
            raise LLMClientError("Anthropic's response was truncated.")
        if response.stop_reason != "end_turn":
            raise LLMClientError("Anthropic did not complete the requested response.")
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise LLMClientError("Anthropic returned no text.")
        return text.strip()
