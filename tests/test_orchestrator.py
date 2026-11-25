import json
from math import nextafter
from types import SimpleNamespace
from unittest.mock import Mock, call, create_autospec

import anthropic
import pytest
from anthropic.types import TextBlock

from judge import JudgeEvaluation, JudgeEvaluationError, StoryJudge
from llm_client import LLMClient, LLMClientError
from orchestrator import AgentOrchestrator, AgentResult, FALLBACK_STORY, TerminationReason
from storyteller import Storyteller

REQUEST = "A fox follows a trail of lanterns."
AGE = 7
DRAFTS = ("Initial draft", "First revision", "Second revision")
SCORES = {
    "age_appropriateness": 5,
    "narrative_coherence": 5,
    "creativity": 5,
    "request_alignment": 5,
    "bedtime_suitability": 5,
}
QUALITY_FEEDBACK = (
    "Improvement: Develop the lantern motif.\n"
    "Improve these rubric areas: age_appropriateness, bedtime_suitability, creativity, "
    "narrative_coherence, request_alignment."
)


def verdict(
    overall: float = 5.0,
    *,
    safety_pass: bool = True,
    feedback: list[str] | None = None,
    overrides: dict[str, int] | None = None,
) -> JudgeEvaluation:
    return JudgeEvaluation(
        safety_pass=safety_pass,
        scores={**SCORES, **(overrides or {})},
        overall_score=overall,
        strengths=["Distinctive setting."],
        feedback=["Develop the lantern motif."] if feedback is None else feedback,
        safety_issues=[] if safety_pass else ["The challenge includes a dangerous dare."],
    )


@pytest.fixture
def agents() -> tuple[Mock, Mock]:
    storyteller = create_autospec(Storyteller, instance=True, spec_set=True)
    storyteller.generate_story.return_value = DRAFTS[0]
    storyteller.revise_story.side_effect = list(DRAFTS[1:])
    judge = create_autospec(StoryJudge, instance=True, spec_set=True)
    judge.evaluate_story.return_value = verdict()
    return storyteller, judge


def assert_fallback(result: AgentResult, reason: TerminationReason) -> None:
    assert result.story == FALLBACK_STORY
    assert result.story not in DRAFTS
    assert not result.accepted
    assert result.used_fallback
    assert result.delivered_evaluation is None
    assert result.termination_reason is reason


@pytest.mark.parametrize("revisions", [0, 1, 2])
def test_stops_at_first_accepted_candidate_in_order(
    agents: tuple[Mock, Mock], revisions: int
) -> None:
    storyteller, judge = agents
    workflow = Mock()
    workflow.attach_mock(storyteller, "storyteller")
    workflow.attach_mock(judge, "judge")
    below_threshold = verdict(4, overrides=dict.fromkeys(SCORES, 4))
    judge.evaluate_story.side_effect = [below_threshold] * revisions + [verdict()]

    result = AgentOrchestrator(storyteller, judge).run_agent(REQUEST, AGE)

    assert result.accepted and not result.used_fallback
    assert result.termination_reason is TerminationReason.ACCEPTED
    assert result.story == DRAFTS[revisions]
    assert result.revision_count == revisions
    assert result.generation_attempts == result.evaluation_attempts == revisions + 1
    assert result.logical_model_calls == 0  # These agents bypass the shared client.
    assert result.latency_seconds >= 0
    assert len(result.evaluation_history) == revisions + 1
    assert result.initial_evaluation is result.evaluation_history[0]
    assert result.delivered_evaluation is result.final_candidate_evaluation
    assert result.final_candidate_evaluation is result.evaluation_history[-1]
    assert result.final_candidate_evaluation.rejection_reasons == ()
    expected = [
        call.storyteller.generate_story(REQUEST, AGE),
        call.judge.evaluate_story(REQUEST, AGE, DRAFTS[0]),
    ]
    for index in range(revisions):
        expected.extend(
            [
                call.storyteller.revise_story(REQUEST, AGE, DRAFTS[index], QUALITY_FEEDBACK),
                call.judge.evaluate_story(REQUEST, AGE, DRAFTS[index + 1]),
            ]
        )
    assert workflow.mock_calls == expected


@pytest.mark.parametrize(
    ("evaluation", "rejection"),
    [
        (verdict(4.0), "overall_score"),
        (verdict(safety_pass=False), "child_safety"),
        (verdict(4.5, overrides={"age_appropriateness": 3}), "age_appropriateness"),
        (verdict(4.5, overrides={"bedtime_suitability": 3}), "bedtime_suitability"),
        (verdict(4.55, overrides={"creativity": 2}), "creativity"),
    ],
)
def test_rejects_all_unacceptable_candidates(
    agents: tuple[Mock, Mock], evaluation: JudgeEvaluation, rejection: str
) -> None:
    storyteller, judge = agents
    judge.evaluate_story.return_value = evaluation

    result = AgentOrchestrator(storyteller, judge).run_agent(REQUEST, AGE)

    assert_fallback(result, TerminationReason.REVISION_LIMIT)
    assert result.revision_count == 2
    assert result.generation_attempts == result.evaluation_attempts == 3
    assert storyteller.revise_story.call_count == 2
    assert judge.evaluate_story.call_args_list == [call(REQUEST, AGE, text) for text in DRAFTS]
    assert [record.rejection_reasons for record in result.evaluation_history] == [(rejection,)] * 3
    assert result.final_candidate_evaluation is result.evaluation_history[-1]
    assert result.final_candidate_evaluation.safety_pass == evaluation.safety_pass
    assert result.final_candidate_evaluation.scores == evaluation.scores
    assert result.final_candidate_evaluation.overall_score == evaluation.overall_score
    assert all(text not in repr(result) for text in DRAFTS)


@pytest.mark.parametrize(
    ("overall", "accepted"), [(4.2, True), (nextafter(4.2, 0.0), True), (4.1999, False)]
)
def test_quality_threshold_boundaries(
    agents: tuple[Mock, Mock], overall: float, accepted: bool
) -> None:
    storyteller, judge = agents
    judge.evaluate_story.return_value = verdict(
        overall,
        overrides={"age_appropriateness": 4, "bedtime_suitability": 4, "creativity": 3},
    )

    result = AgentOrchestrator(storyteller, judge).run_agent(REQUEST, AGE)

    assert result.accepted is accepted
    if accepted:
        storyteller.revise_story.assert_not_called()
    else:
        assert_fallback(result, TerminationReason.REVISION_LIMIT)


def test_feedback_includes_safety_concerns_and_quality_targets(agents: tuple[Mock, Mock]) -> None:
    storyteller, judge = agents
    judge.evaluate_story.side_effect = [
        verdict(4.4, safety_pass=False, overrides={"age_appropriateness": 3}),
        verdict(),
    ]

    result = AgentOrchestrator(storyteller, judge).run_agent(REQUEST, AGE)

    assert result.story == DRAFTS[1]
    storyteller.revise_story.assert_called_once_with(
        REQUEST,
        AGE,
        DRAFTS[0],
        "Improvement: Develop the lantern motif.\n"
        "Safety concern to remove or safely replace: The challenge includes a dangerous dare.\n"
        "Improve these rubric areas: age_appropriateness.",
    )
    assert result.initial_evaluation.rejection_reasons == ("child_safety", "age_appropriateness")


def test_supplies_revision_targets_when_judge_feedback_is_empty(agents: tuple[Mock, Mock]) -> None:
    storyteller, judge = agents
    judge.evaluate_story.side_effect = [
        verdict(4, feedback=[], overrides=dict.fromkeys(SCORES, 4)), verdict()
    ]

    assert AgentOrchestrator(storyteller, judge).run_agent(REQUEST, AGE).accepted
    assert storyteller.revise_story.call_args.args[3].startswith("Improve these rubric areas:")


def test_initial_generation_error_uses_fallback(agents: tuple[Mock, Mock]) -> None:
    storyteller, judge = agents
    storyteller.generate_story.side_effect = LLMClientError("Could not connect.")

    result = AgentOrchestrator(storyteller, judge).run_agent(REQUEST, AGE)

    assert_fallback(result, TerminationReason.GENERATION_ERROR)
    assert result.generation_attempts == 1
    assert result.evaluation_attempts == result.revision_count == 0
    assert result.initial_evaluation is result.final_candidate_evaluation is None
    judge.evaluate_story.assert_not_called()


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (JudgeEvaluationError("Invalid JSON."), TerminationReason.INVALID_EVALUATION),
        (LLMClientError("Timed out."), TerminationReason.EVALUATION_ERROR),
    ],
)
def test_judge_failure_on_revision_does_not_reuse_previous_verdict(
    agents: tuple[Mock, Mock], error: RuntimeError, reason: TerminationReason
) -> None:
    storyteller, judge = agents
    judge.evaluate_story.side_effect = [verdict(4.0), error]

    result = AgentOrchestrator(storyteller, judge).run_agent(REQUEST, AGE)

    assert_fallback(result, reason)
    assert result.final_candidate_evaluation is None
    assert result.initial_evaluation is result.evaluation_history[0]
    assert result.revision_count == len(result.evaluation_history) == 1
    assert result.generation_attempts == result.evaluation_attempts == 2
    storyteller.revise_story.assert_called_once()


@pytest.mark.parametrize("invalid_evaluation", [{"safety_pass": True}, verdict()])
def test_incomplete_verdict_never_releases_draft(
    agents: tuple[Mock, Mock], invalid_evaluation: object
) -> None:
    storyteller, judge = agents
    if isinstance(invalid_evaluation, JudgeEvaluation):
        invalid_evaluation.scores.pop("bedtime_suitability", None)
    judge.evaluate_story.return_value = invalid_evaluation

    result = AgentOrchestrator(storyteller, judge).run_agent(REQUEST, AGE)

    assert_fallback(result, TerminationReason.INVALID_EVALUATION)
    assert result.evaluation_history == ()
    storyteller.revise_story.assert_not_called()


def test_refinement_error_preserves_only_last_completed_assessment(agents: tuple[Mock, Mock]) -> None:
    storyteller, judge = agents
    judge.evaluate_story.return_value = verdict(4.0)
    storyteller.revise_story.side_effect = LLMClientError("Timed out.")

    result = AgentOrchestrator(storyteller, judge).run_agent(REQUEST, AGE)

    assert_fallback(result, TerminationReason.REFINEMENT_ERROR)
    assert result.final_candidate_evaluation is result.initial_evaluation
    assert result.revision_count == 0
    assert result.generation_attempts == 2
    assert result.evaluation_attempts == 1


@pytest.mark.parametrize(
    ("request_text", "age"),
    [("", 7), (" \t", 7), (None, 7), ("A fox", 4), ("A fox", 11), ("A fox", True), ("A fox", 7.0)],
)
def test_invalid_input_never_runs_workflow(
    agents: tuple[Mock, Mock], request_text: str, age: int
) -> None:
    storyteller, judge = agents
    with pytest.raises(ValueError):
        AgentOrchestrator(storyteller, judge).run_agent(request_text, age)
    storyteller.generate_story.assert_not_called()
    judge.evaluate_story.assert_not_called()


def response(text: str) -> SimpleNamespace:
    return SimpleNamespace(stop_reason="end_turn", content=[TextBlock(type="text", text=text)])


@pytest.mark.parametrize("correction_succeeds", [True, False])
def test_counts_real_client_calls_and_bounds_judge_correction(correction_succeeds: bool) -> None:
    sdk = Mock(spec=anthropic.Anthropic)
    valid = json.dumps(
        {"safety_pass": True, "scores": SCORES, "strengths": [], "feedback": [], "safety_issues": []}
    )
    sdk.messages.create.side_effect = [
        response(DRAFTS[0]),
        response("Invalid JSON"),
        response(valid if correction_succeeds else "Still invalid"),
    ]
    client = LLMClient(sdk)

    result = AgentOrchestrator(Storyteller(client), StoryJudge(client)).run_agent(REQUEST, AGE)

    assert result.logical_model_calls == sdk.messages.create.call_count == 3
    assert result.generation_attempts == result.evaluation_attempts == 1
    if correction_succeeds:
        assert result.accepted
        assert result.delivered_evaluation is not None
    else:
        assert_fallback(result, TerminationReason.INVALID_EVALUATION)
        assert result.evaluation_history == ()


def test_full_workflow_makes_at_most_nine_logical_calls_with_corrections() -> None:
    sdk = Mock(spec=anthropic.Anthropic)
    rejected = json.dumps(
        {
            "safety_pass": True,
            "scores": dict.fromkeys(SCORES, 4),
            "strengths": [],
            "feedback": [],
            "safety_issues": [],
        }
    )
    sdk.messages.create.side_effect = [
        response(text) for draft in DRAFTS for text in (draft, "Invalid JSON", rejected)
    ]
    client = LLMClient(sdk)

    result = AgentOrchestrator(Storyteller(client), StoryJudge(client)).run_agent(REQUEST, AGE)

    assert_fallback(result, TerminationReason.REVISION_LIMIT)
    assert result.logical_model_calls == sdk.messages.create.call_count == 9
    assert result.generation_attempts == result.evaluation_attempts == 3


def test_call_count_resets_between_workflows_and_includes_failed_sdk_request() -> None:
    sdk = Mock(spec=anthropic.Anthropic)
    sdk.messages.create.return_value = SimpleNamespace(stop_reason="refusal", content=[])
    client = LLMClient(sdk)
    agent = AgentOrchestrator(Storyteller(client), StoryJudge(client))

    for _ in range(2):
        result = agent.run_agent(REQUEST, AGE)
        assert_fallback(result, TerminationReason.GENERATION_ERROR)
        assert result.logical_model_calls == 1
    assert sdk.messages.create.call_count == 2
