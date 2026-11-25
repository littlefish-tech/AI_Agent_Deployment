import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import anthropic
import httpx2
import pytest
from anthropic.types import TextBlock, ThinkingBlock

import config
import llm_client
from llm_client import (
    LLMClient,
    LLMClientError,
    WorkflowDeadlineExceeded,
    track_model_calls,
    workflow_deadline,
)

bounded_sdk = llm_client._BoundedAnthropic


@pytest.fixture(autouse=True)
def default_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")


@pytest.fixture
def sdk_client() -> Mock:
    return Mock(spec=anthropic.Anthropic)


def test_client_smoke(sdk_client: Mock) -> None:
    sdk_client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[TextBlock(type="text", text=" Sleep well. ")]
    )

    assert LLMClient(sdk_client).generate_text(
        system_prompt="Write a bedtime story.", user_message="A sleepy fox"
    ) == "Sleep well."
    assert config.MODEL_ID == "claude-haiku-5-5"
    sdk_client.messages.create.assert_called_once_with(
        model="claude-haiku-5-5",
        max_tokens=config.DEFAULT_MAX_OUTPUT_TOKENS,
        system="Write a bedtime story.",
        messages=[{"role": "user", "content": "A sleepy fox"}],
    )


def test_combines_text_blocks_and_passes_token_override(sdk_client: Mock) -> None:
    sdk_client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn",
        content=[
            TextBlock(type="text", text="Once upon "),
            ThinkingBlock(type="thinking", thinking="Internal reasoning", signature="test"),
            TextBlock(type="text", text="a time."),
        ],
    )

    assert LLMClient(sdk_client).generate_text(
        system_prompt="System", user_message="User", max_output_tokens=256
    ) == "Once upon a time."
    assert sdk_client.messages.create.call_args.kwargs["max_tokens"] == 256


def test_sends_native_json_schema_when_requested(sdk_client: Mock) -> None:
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    sdk_client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[TextBlock(type="text", text="{}")]
    )

    result = LLMClient(sdk_client).generate_text(
        system_prompt="System", user_message="User", json_schema=schema
    )

    assert result == "{}"
    assert sdk_client.messages.create.call_args.kwargs["output_config"] == {
        "format": {"type": "json_schema", "schema": schema}
    }


@pytest.mark.parametrize("env_value", [None, " ", "environment-test-value"])
def test_credential_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_value: str | None
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("ANTHROPIC_API_KEY='dotenv-test-value'\n", encoding="utf-8")
    monkeypatch.setattr(config, "DOTENV_PATH", dotenv_path)
    if env_value is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", env_value)

    with patch("llm_client._BoundedAnthropic") as constructor:
        if env_value == " ":
            with pytest.raises(LLMClientError, match="Set ANTHROPIC_API_KEY"):
                LLMClient()
            constructor.assert_not_called()
        else:
            LLMClient()
            constructor.assert_called_once_with(
                api_key=env_value or "dotenv-test-value",
                base_url="https://api.anthropic.com",
                timeout=30.0,
                max_retries=2,
            )


def test_openrouter_messages_route_and_json_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=gateway-test-token\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "DOTENV_PATH", dotenv_path)
    monkeypatch.delenv("LLM_PROVIDER")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "direct-test-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://other.example")
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "model": config.OPENROUTER_MODEL_ID,
                "type": "message",
                "role": "assistant",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "{}"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    with httpx2.Client(transport=httpx2.MockTransport(respond)) as transport:
        with patch(
            "llm_client._BoundedAnthropic",
            side_effect=lambda **kwargs: bounded_sdk(http_client=transport, **kwargs),
        ):
            client = LLMClient()
            assert client.generate_text(system_prompt="System", user_message="User") == "{}"
            assert client.generate_text(
                system_prompt="Judge", user_message="Draft", json_schema={"type": "object"}
            ) == "{}"
    assert client.model_id == "anthropic/claude-haiku-5.5"
    assert len(requests) == 2
    for request in requests:
        assert str(request.url) == "https://openrouter.ai/api/v1/messages"
        assert request.headers["Authorization"] == "Bearer gateway-test-token"
        assert "x-api-key" not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == client.model_id
        assert not {"models", "fallbacks", "temperature", "top_p", "top_k"} & payload.keys()
    assert "output_config" not in json.loads(requests[0].content)
    assert json.loads(requests[1].content)["output_config"] == {
        "format": {"type": "json_schema", "schema": {"type": "object"}}
    }


def test_openrouter_does_not_use_direct_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "direct-test-token")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch("llm_client._BoundedAnthropic") as constructor:
        with pytest.raises(LLMClientError, match="Set OPENROUTER_API_KEY"):
            LLMClient()
    constructor.assert_not_called()


def test_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "unsupported")
    with patch("llm_client._BoundedAnthropic") as constructor:
        with pytest.raises(LLMClientError, match="Set LLM_PROVIDER"):
            LLMClient()
    constructor.assert_not_called()


def test_sdk_retries_rate_limit_only_twice_and_counts_one_logical_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "mock-retry-credential")
    sleep = Mock()
    monkeypatch.setattr("anthropic._base_client.time.sleep", sleep)
    attempts = Mock(
        side_effect=lambda request: httpx2.Response(
            429,
            headers={"retry-after": "3600"},
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limited"}},
        )
    )
    with httpx2.Client(transport=httpx2.MockTransport(attempts)) as transport:
        with patch(
            "llm_client._BoundedAnthropic",
            side_effect=lambda **kwargs: bounded_sdk(http_client=transport, **kwargs),
        ):
            client = LLMClient()
            with track_model_calls(limit=1) as budget, track_model_calls() as inner:
                with pytest.raises(LLMClientError, match="rate limit"):
                    client.generate_text(system_prompt="System", user_message="User")
    assert budget.count == inner.count == 1
    assert attempts.call_count == 3
    assert [attempt.args[0] for attempt in sleep.call_args_list] == [5.0, 5.0]


@pytest.mark.parametrize(
    ("deadline", "oversleep", "timeouts", "sleeps"),
    [
        (106.0, 0.0, [6.0, 1.0], [5.0]),
        (105.0, 0.0, [5.0], []),
        (106.0, 1.0, [6.0], [5.0]),
    ],
)
def test_sdk_retry_wait_and_attempts_respect_the_workflow_deadline(
    monkeypatch: pytest.MonkeyPatch, deadline: float, oversleep: float,
    timeouts: list[float], sleeps: list[float],
) -> None:
    now = 100.0
    observed_timeouts: list[float] = []
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        nonlocal now
        slept.append(seconds)
        now += seconds + oversleep

    def respond(request: httpx2.Request) -> httpx2.Response:
        observed_timeouts.append(request.extensions["timeout"]["read"])
        if len(observed_timeouts) == 1:
            return httpx2.Response(429, headers={"retry-after": "3600"}, json={})
        return httpx2.Response(
            200,
            json={
                "id": "msg_test", "model": config.MODEL_ID, "type": "message",
                "role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "A story"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    monkeypatch.setattr(llm_client, "perf_counter", lambda: now)
    monkeypatch.setattr("anthropic._base_client.time.sleep", sleep)
    with httpx2.Client(transport=httpx2.MockTransport(respond)) as transport:
        client = LLMClient(bounded_sdk(api_key="mock-key", http_client=transport))
        with track_model_calls() as calls, workflow_deadline(deadline):
            if len(timeouts) == 2:
                assert client.generate_text(system_prompt="System", user_message="User") == "A story"
            else:
                with pytest.raises(WorkflowDeadlineExceeded):
                    client.generate_text(system_prompt="System", user_message="User")

    assert calls.count == 1
    assert observed_timeouts == timeouts
    assert slept == sleeps


def test_missing_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "DOTENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("llm_client._BoundedAnthropic") as constructor:
        with pytest.raises(LLMClientError, match="Set ANTHROPIC_API_KEY"):
            LLMClient()
    constructor.assert_not_called()


def test_invalid_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_bytes(b"\xff")
    monkeypatch.setattr(config, "DOTENV_PATH", dotenv_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(LLMClientError, match="Could not read the local"):
        LLMClient()


@pytest.mark.parametrize("content", [[], [TextBlock(type="text", text=" \n")]])
def test_rejects_empty_text(sdk_client: Mock, content: list[TextBlock]) -> None:
    sdk_client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=content
    )
    with pytest.raises(LLMClientError, match="returned no text"):
        LLMClient(sdk_client).generate_text(system_prompt="System", user_message="User")


@pytest.mark.parametrize(
    ("stop_reason", "error_message"),
    [
        ("max_tokens", "was truncated"),
        ("model_context_window_exceeded", "was truncated"),
        ("refusal", "did not complete"),
        ("pause_turn", "did not complete"),
        (None, "did not complete"),
    ],
)
def test_rejects_incomplete_response(
    sdk_client: Mock, stop_reason: str | None, error_message: str
) -> None:
    sdk_client.messages.create.return_value = SimpleNamespace(
        stop_reason=stop_reason, content=[TextBlock(type="text", text="Partial output")]
    )
    with pytest.raises(LLMClientError, match=error_message):
        LLMClient(sdk_client).generate_text(system_prompt="System", user_message="User")


@pytest.mark.parametrize(
    ("system_prompt", "user_message", "max_output_tokens"),
    [("", "User", 100), ("System", " ", 100), ("System", "User", 0), ("System", "User", True)],
)
def test_validates_input_before_calling_api(
    sdk_client: Mock, system_prompt: str, user_message: str, max_output_tokens: int
) -> None:
    with pytest.raises(ValueError):
        LLMClient(sdk_client).generate_text(
            system_prompt=system_prompt,
            user_message=user_message,
            max_output_tokens=max_output_tokens,
        )
    sdk_client.messages.create.assert_not_called()


@pytest.mark.parametrize(
    ("error_type", "status", "message"),
    [
        (anthropic.AuthenticationError, 401, "rejected the credentials"),
        (anthropic.PermissionDeniedError, 403, "rejected the credentials"),
        (anthropic.NotFoundError, 404, "required Anthropic model is unavailable"),
        (anthropic.RequestTimeoutError, 408, "request timed out"),
        (anthropic.RateLimitError, 429, "rate limit"),
        (anthropic.InternalServerError, 500, "server error"),
        (anthropic.BadRequestError, 400, "request failed"),
    ],
)
def test_handles_api_status_errors(
    sdk_client: Mock, error_type: type[anthropic.APIStatusError], status: int, message: str
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    sdk_client.messages.create.side_effect = error_type(
        "sensitive upstream detail", response=httpx2.Response(status, request=request), body=None
    )
    with pytest.raises(LLMClientError, match=message) as caught:
        LLMClient(sdk_client).generate_text(system_prompt="System", user_message="User")
    assert "sensitive upstream detail" not in str(caught.value)
    assert caught.value.__suppress_context__
    sdk_client.messages.create.assert_called_once()


@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (anthropic.APITimeoutError, "request timed out"),
        (anthropic.APIConnectionError, "Could not connect"),
    ],
)
def test_handles_transport_errors(
    sdk_client: Mock, error_type: type[anthropic.APIConnectionError], message: str
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    sdk_client.messages.create.side_effect = error_type(request=request)
    with pytest.raises(LLMClientError, match=message):
        LLMClient(sdk_client).generate_text(system_prompt="System", user_message="User")
    sdk_client.messages.create.assert_called_once()
