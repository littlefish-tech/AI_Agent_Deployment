"""Shared text-only client for the storyteller and judge."""

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
    DEFAULT_MAX_OUTPUT_TOKENS,
    MAX_RETRIES,
    MODEL_ID,
    REQUEST_TIMEOUT_SECONDS,
    get_anthropic_api_key,
)


class LLMClientError(RuntimeError):
    """A client failure with a message safe to display."""


class LLMClient:
    """Make synchronous, single-turn requests through a reusable Anthropic client."""

    def __init__(self, client: Anthropic | None = None) -> None:
        """Use an injected SDK client or configure one from local credentials."""
        if client is None:
            try:
                api_key = get_anthropic_api_key()
            except (OSError, UnicodeError):
                raise LLMClientError("Could not read the local .env file.") from None
            if not api_key:
                raise LLMClientError("Set ANTHROPIC_API_KEY in the environment or .env.")
            client = Anthropic(
                api_key=api_key,
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_retries=MAX_RETRIES,
            )
        self._client = client

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

        try:
            response = self._client.messages.create(
                model=MODEL_ID,
                max_tokens=max_output_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                **(
                    {"output_config": {"format": {"type": "json_schema", "schema": json_schema}}}
                    if json_schema is not None
                    else {}
                ),
            )
        except (AuthenticationError, PermissionDeniedError):
            raise LLMClientError("Anthropic rejected the credentials or access.") from None
        except RateLimitError:
            raise LLMClientError("Anthropic's rate limit was reached.") from None
        except (APITimeoutError, RequestTimeoutError):
            raise LLMClientError("The Anthropic request timed out.") from None
        except APIConnectionError:
            raise LLMClientError("Could not connect to Anthropic.") from None
        except InternalServerError:
            raise LLMClientError("Anthropic returned a server error.") from None
        except NotFoundError:
            raise LLMClientError("The required Anthropic model is unavailable.") from None
        except APIError:
            raise LLMClientError("The Anthropic request failed.") from None

        if response.stop_reason in {"max_tokens", "model_context_window_exceeded"}:
            raise LLMClientError("Anthropic's response was truncated.")
        if response.stop_reason != "end_turn":
            raise LLMClientError("Anthropic did not complete the requested response.")
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise LLMClientError("Anthropic returned no text.")
        return text.strip()
