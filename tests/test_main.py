import json
from types import SimpleNamespace
from unittest.mock import Mock

import anthropic
import httpx2
import pytest
from anthropic.types import TextBlock

import llm_client
import main
from config import MAX_STORY_REQUEST_LENGTH, MODEL_ID
from orchestrator import AgentResult, CandidateAssessment, FALLBACK_STORY, TerminationReason

STORY = "The Sleepy Fox\n\nThe little fox curled up beside the moonlit stream."
REQUEST = "A fox and a moonlit stream"
TEST_CREDENTIAL = "test-credential-private"
SCORES = {
    "age_appropriateness": 5,
    "narrative_coherence": 4,
    "creativity": 4,
    "request_alignment": 5,
    "bedtime_suitability": 5,
}


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock_sdk = Mock(spec=anthropic.Anthropic)
    monkeypatch.setattr(llm_client, "Anthropic", Mock(return_value=mock_sdk))
    monkeypatch.setattr(llm_client, "get_anthropic_api_key", lambda: TEST_CREDENTIAL)
    return mock_sdk


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> Mock:
    assessment = CandidateAssessment(SCORES, 4.65, True, ())
    result = AgentResult(
        story=STORY,
        accepted=True,
        used_fallback=False,
        final_candidate_evaluation=assessment,
        evaluation_history=(assessment,),
        revision_count=0,
        generation_attempts=1,
        evaluation_attempts=1,
        logical_model_calls=2,
        latency_seconds=1.25,
        termination_reason=TerminationReason.ACCEPTED,
    )
    mock_agent = Mock(spec=main.AgentOrchestrator)
    mock_agent.run_agent.return_value = result
    monkeypatch.setattr(main, "AgentOrchestrator", Mock(return_value=mock_agent))
    return mock_agent


def feed_input(monkeypatch: pytest.MonkeyPatch, *answers: str) -> Mock:
    prompt = Mock(side_effect=answers)
    monkeypatch.setattr("builtins.input", prompt)
    return prompt


@pytest.mark.parametrize(("age_input", "expected_age"), [("", 7), (" 10 ", 10), ("5", 5)])
def test_displays_accepted_story_with_shared_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    sdk: Mock, agent: Mock, age_input: str, expected_age: int,
) -> None:
    prompt = feed_input(monkeypatch, f" {REQUEST} ", age_input)

    assert main.main([]) == 0

    agent.run_agent.assert_called_once_with(REQUEST, expected_age, on_progress=main._report_progress)
    storyteller, judge = main.AgentOrchestrator.call_args.args
    assert storyteller._client is judge._client
    assert "default 7" in prompt.call_args.args[0]
    sdk.messages.create.assert_not_called()
    output = capsys.readouterr()
    assert "Welcome!" in output.out
    assert "Your bedtime story is ready!" in output.out
    assert STORY in output.out
    assert "Execution details" not in output.out
    assert "Generating your bedtime story..." not in output.out
    assert MODEL_ID not in output.out
    assert output.err == ""


@pytest.mark.parametrize(
    ("answers", "expected_text", "expected_age"),
    [
        (("", REQUEST, "7"), "enter a bedtime story idea", 7),
        ((" \t", REQUEST, "7"), "enter a bedtime story idea", 7),
        (("x" * (MAX_STORY_REQUEST_LENGTH + 1), REQUEST, "7"), "2,000 characters", 7),
        ((REQUEST, "seven", "8"), "whole number", 8),
        ((REQUEST, "7.5", "7"), "whole number", 7),
        ((REQUEST, "4", "5"), "from 5 to 10", 5),
        ((REQUEST, "11", "10"), "from 5 to 10", 10),
    ],
)
def test_reprompts_before_initializing_any_api_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sdk: Mock, agent: Mock,
    answers: tuple[str, ...], expected_text: str, expected_age: int,
) -> None:
    pending = iter(answers)

    def respond(prompt: str) -> str:
        llm_client.Anthropic.assert_not_called()
        agent.run_agent.assert_not_called()
        return next(pending)

    monkeypatch.setattr("builtins.input", respond)

    assert main.main([]) == 0

    assert expected_text in capsys.readouterr().out
    agent.run_agent.assert_called_once_with(REQUEST, expected_age, on_progress=main._report_progress)
    assert llm_client.Anthropic.call_count == 1
    sdk.messages.create.assert_not_called()


def test_debug_displays_existing_metrics(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sdk: Mock, agent: Mock,
) -> None:
    feed_input(monkeypatch, REQUEST, "")

    assert main.main(["--debug"]) == 0

    output = capsys.readouterr().out
    for expected in (
        MODEL_ID, "Initial candidate quality: 4.65/5", "Final candidate quality: 4.65/5",
        "Age appropriateness: 5/5", "Creativity: 4/5", "child safety passed", "Accepted: yes",
        "Fallback used: no", "Completed revisions: 0", "Logical LLM calls: 2",
        "Execution latency: 1.25s", "Termination reason: accepted",
    ):
        assert expected in output
    assert TEST_CREDENTIAL not in output


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
@pytest.mark.parametrize("inputs_before_error", [[], [REQUEST]])
def test_input_interruption_exits_without_calling_api(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    sdk: Mock, error: type[BaseException], inputs_before_error: list[str],
) -> None:
    monkeypatch.setattr("builtins.input", Mock(side_effect=[*inputs_before_error, error()]))

    assert main.main([]) == (0 if error is EOFError else 130)

    output = capsys.readouterr()
    if error is EOFError:
        assert "Good night!" in output.out
    else:
        assert "cancelled" in output.err
    llm_client.Anthropic.assert_not_called()
    sdk.messages.create.assert_not_called()


def test_missing_api_key_reports_setup_without_sdk_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sdk: Mock,
) -> None:
    feed_input(monkeypatch, REQUEST, "")
    monkeypatch.setattr(llm_client, "get_anthropic_api_key", lambda: None)

    assert main.main(["--debug"]) == 1

    output = capsys.readouterr()
    assert "Check that ANTHROPIC_API_KEY" in output.err
    assert "Execution details" not in output.out
    llm_client.Anthropic.assert_not_called()
    sdk.messages.create.assert_not_called()


def response(text: str) -> SimpleNamespace:
    return SimpleNamespace(stop_reason="end_turn", content=[TextBlock(type="text", text=text)])


def verdict(*, safe: bool = True) -> str:
    return json.dumps(
        {
            "safety_pass": safe,
            "scores": SCORES,
            "strengths": ["Internal strengths"],
            "feedback": [] if safe else ["Private revision feedback"],
            "safety_issues": [] if safe else ["Private safety issue"],
        }
    )


def test_real_progress_reflects_generation_revision_and_reevaluation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sdk: Mock,
) -> None:
    feed_input(monkeypatch, REQUEST, "8")
    rejected = "Rejected private draft"
    sdk.messages.create.side_effect = [
        response(rejected), response(verdict(safe=False)), response(STORY), response(verdict()),
    ]

    assert main.main([]) == 0

    output = capsys.readouterr().out
    events = [
        "Generating your bedtime story...",
        "Evaluating story quality and age appropriateness...",
        "Improving the story based on feedback...",
        "Reevaluating the revised story...",
        "Your bedtime story is ready!",
    ]
    assert [line for line in output.splitlines() if line in events] == events
    assert STORY in output
    assert rejected not in output
    assert "Private revision feedback" not in output
    assert "Private safety issue" not in output
    assert sdk.messages.create.call_count == 4
    assert all(call.kwargs["model"] == MODEL_ID for call in sdk.messages.create.call_args_list)


def test_fallback_debug_keeps_rejected_candidate_scores_separate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sdk: Mock,
) -> None:
    feed_input(monkeypatch, REQUEST, "7")
    sdk.messages.create.side_effect = [
        response(text)
        for index in range(3)
        for text in (f"Private rejected draft {index}", verdict(safe=False))
    ]

    assert main.main(["--debug"]) == 0

    output = capsys.readouterr().out
    assert FALLBACK_STORY in output
    assert "prewritten bedtime story instead" in output
    assert "Your bedtime story is ready!" not in output
    assert "Final candidate quality:" in output
    assert "child safety failed" in output
    assert "Delivered story: prewritten fallback (no evaluation score)" in output
    assert "Accepted: no" in output
    assert "Fallback used: yes" in output
    assert "Completed revisions: 2" in output
    assert "Logical LLM calls: 6" in output
    assert "Termination reason: revision_limit" in output
    assert "Private" not in output


@pytest.mark.parametrize("failure", ["authentication", "rate_limit", "timeout", "connection", "judge"])
def test_runtime_failure_returns_fallback_without_exposing_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sdk: Mock, failure: str,
) -> None:
    feed_input(monkeypatch, REQUEST, "")
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    failures = {
        "authentication": anthropic.AuthenticationError(
            TEST_CREDENTIAL, response=httpx2.Response(401, request=request), body=None
        ),
        "rate_limit": anthropic.RateLimitError(
            TEST_CREDENTIAL, response=httpx2.Response(429, request=request), body=None
        ),
        "timeout": anthropic.APITimeoutError(request=request),
        "connection": anthropic.APIConnectionError(message=TEST_CREDENTIAL, request=request),
    }
    if failure == "judge":
        sdk.messages.create.side_effect = [
            response("Private draft"), response("bad JSON"), response("bad JSON")
        ]
    else:
        sdk.messages.create.side_effect = failures[failure]

    assert main.main(["--debug"]) == 0

    output = capsys.readouterr().out
    assert FALLBACK_STORY in output
    assert "Generating your bedtime story..." in output
    assert "Improving the story based on feedback..." not in output
    assert "Final candidate quality: evaluation unavailable" in output
    assert TEST_CREDENTIAL not in output
    assert "Private draft" not in output
    if failure == "judge":
        assert "The story checks returned an unusable result." in output
        assert "Termination reason: invalid_evaluation" in output
        assert sdk.messages.create.call_count == 3
    else:
        assert "The story service could not generate a draft." in output
        assert "Evaluating story quality" not in output
        assert sdk.messages.create.call_count == 1


def test_unexpected_errors_are_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, sdk: Mock, agent: Mock,
) -> None:
    feed_input(monkeypatch, REQUEST, "7")
    agent.run_agent.side_effect = RuntimeError("Unexpected programming error")

    with pytest.raises(RuntimeError, match="Unexpected programming error"):
        main.main([])


def test_request_at_length_limit_is_accepted(
    monkeypatch: pytest.MonkeyPatch, sdk: Mock, agent: Mock,
) -> None:
    request = "x" * MAX_STORY_REQUEST_LENGTH
    feed_input(monkeypatch, request, "")

    assert main.main([]) == 0

    agent.run_agent.assert_called_once_with(request, 7, on_progress=main._report_progress)


def test_interrupt_during_generation_exits_without_printing_a_story(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sdk: Mock,
) -> None:
    feed_input(monkeypatch, REQUEST, "")
    sdk.messages.create.side_effect = KeyboardInterrupt

    assert main.main([]) == 130

    output = capsys.readouterr()
    assert "cancelled" in output.err
    assert "Generating your bedtime story..." in output.out
    assert "Evaluating story quality" not in output.out
    assert FALLBACK_STORY not in output.out
