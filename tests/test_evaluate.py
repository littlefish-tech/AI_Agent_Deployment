import csv
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import anthropic
import pytest
from anthropic.types import TextBlock

import evaluate
from config import JUDGE_WEIGHTS
from judge import JudgeEvaluationError, StoryJudge
from llm_client import LLMClient, LLMClientError, ModelCallBudgetExceeded
from orchestrator import AgentOrchestrator, AgentResult, CandidateAssessment, TerminationReason
from storyteller import Storyteller

CASES = (
    evaluate.EvaluationCase("first", "A little fox.", 5, "animal", "A gentle adventure."),
    evaluate.EvaluationCase("second", "A clever rabbit.", 7, "animal", "A reassuring ending."),
    evaluate.EvaluationCase("third", "A sleepy owl.", 10, "animal", "A coherent story."),
)
REJECTED_STORY = "private rejected story"
PRIVATE_PROVIDER_DETAIL = "private-provider-credential-or-response"


def assessment(score: float, *, safety: bool = True, creativity: int = 4) -> CandidateAssessment:
    return CandidateAssessment(
        {**dict.fromkeys(JUDGE_WEIGHTS, 4), "creativity": creativity},
        score,
        safety,
        () if safety else ("child_safety",),
    )


def result(
    *history: CandidateAssessment,
    accepted: bool = False,
    reason: TerminationReason = TerminationReason.REVISION_LIMIT,
    revisions: int = 0,
    attempts: int | None = None,
    final_missing: bool = False,
    calls: int = 2,
) -> AgentResult:
    return AgentResult(
        story=REJECTED_STORY,
        accepted=accepted,
        used_fallback=not accepted,
        final_candidate_evaluation=history[-1] if history and not final_missing else None,
        evaluation_history=history,
        revision_count=revisions,
        generation_attempts=revisions + 1 if attempts is None else attempts,
        evaluation_attempts=len(history),
        logical_model_calls=calls,
        latency_seconds=float(calls) / 10,
        termination_reason=reason,
    )


def write_dataset(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_bundled_dataset_and_subset() -> None:
    cases = evaluate.load_cases(evaluate.DEFAULT_DATASET)
    assert len(cases) == 10
    assert [case.age for case in cases] == [7, 5, 6, 9, 5, 10, 7, 6, 8, 9]
    assert len({case.case_id for case in cases}) == 10
    assert all(case.expected_behavior for case in cases)
    assert [case.case_id for case in evaluate.select_cases(cases, ["safety-injection", "alice-and-bob"])] == [
        "alice-and-bob", "safety-injection",
    ]
    with pytest.raises(ValueError, match="selected case IDs"):
        evaluate.select_cases(cases, ["unknown"])


_VALID_ROW = {
    "id": "case-a", "request": "A rabbit.", "age": 5, "category": "animal", "expected_behavior": "Gentle."
}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        [None],
        [{"id": "missing-fields"}],
        [{**_VALID_ROW, "id": "|bad"}],
        [{**_VALID_ROW, "request": " "}],
        [{**_VALID_ROW, "age": True}],
        [{**_VALID_ROW, "age": 11}],
        [{**_VALID_ROW, "category": ""}],
        [{**_VALID_ROW, "expected_behavior": []}],
        [_VALID_ROW, _VALID_ROW],
    ],
)
def test_rejects_invalid_dataset(tmp_path: Path, payload: object) -> None:
    with pytest.raises(ValueError, match="evaluation"):
        evaluate.load_cases(write_dataset(tmp_path / "cases.json", payload))


def test_rejects_broken_json_and_missing_dataset(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    with pytest.raises(ValueError, match="Could not read"):
        evaluate.load_cases(path)
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not read"):
        evaluate.load_cases(path)


def test_compares_only_revised_candidates_with_both_assessments() -> None:
    initial = assessment(3.8, safety=False, creativity=2)
    final = assessment(4.4)
    row = evaluate.collect_result(
        CASES[0], result(initial, final, accepted=True, reason=TerminationReason.ACCEPTED, revisions=1, calls=4)
    )
    assert row.outcome == "refined_accepted"
    assert row.logical_calls == 4 and row.latency_seconds == 0.4
    assert row.comparison is not None
    assert row.comparison.quality_change == pytest.approx(0.6)
    assert row.comparison.criterion_changes == {**dict.fromkeys(JUDGE_WEIGHTS, 0), "creativity": 2}
    assert row.comparison.safety_improved and not row.comparison.safety_regressed
    assert row.delivered_evaluation is final

    row = evaluate.collect_result(CASES[0], result(final, initial, revisions=2, calls=6))
    assert row.outcome == "unsuccessful_refinement"
    assert row.used_fallback and row.delivered_evaluation is None
    assert row.final_candidate is initial
    assert row.comparison is not None
    assert row.comparison.quality_change == pytest.approx(-0.6)
    assert row.comparison.safety_regressed and not row.comparison.safety_improved

    unchanged = evaluate.collect_result(CASES[0], result(final, accepted=True, reason=TerminationReason.ACCEPTED))
    assert unchanged.outcome == "first_pass_accepted"
    assert unchanged.comparison is None

    missing = evaluate.collect_result(
        CASES[0], result(initial, reason=TerminationReason.INVALID_EVALUATION, revisions=1, final_missing=True)
    )
    assert missing.comparison is missing.final_candidate is missing.delivered_evaluation is None
    assert missing.error == "invalid_evaluation"


def test_aggregate_uses_explicit_denominators_and_excludes_unmeasured_scores() -> None:
    good, failed, final_failed = assessment(4.6), assessment(3.6, safety=False), assessment(3.4)
    rows = [
        evaluate.collect_result(CASES[0], result(good, accepted=True, reason=TerminationReason.ACCEPTED)),
        evaluate.collect_result(
            CASES[1], result(failed, good, accepted=True, reason=TerminationReason.ACCEPTED, revisions=1, calls=4)
        ),
        evaluate.collect_result(CASES[2], result(failed, final_failed, revisions=2, calls=6)),
        evaluate.collect_result(
            CASES[2], result(failed, reason=TerminationReason.REFINEMENT_ERROR, attempts=2, calls=3)
        ),
        evaluate.collect_result(CASES[2], result(reason=TerminationReason.EVALUATION_ERROR, calls=2)),
    ]
    metrics = evaluate.aggregate(rows)
    assert metrics["total_evaluation_requests"] == 5
    assert metrics["total_logical_calls"] == 17
    for key, numerator, denominator in (
        ("first_pass_acceptance_rate", 1, 5),
        ("final_generated_acceptance_rate", 2, 5),
        ("revision_success_rate", 1, 3),
        ("initial_judge_safety_pass_rate", 1, 4),
        ("final_judge_safety_pass_rate", 3, 4),
        ("fallback_rate", 3, 5),
        ("evaluation_error_rate", 2, 5),
    ):
        assert metrics[key] == {"value": numerator / denominator, "numerator": numerator, "denominator": denominator}
    for key, value, denominator in (
        ("average_initial_quality", 3.85, 4),
        ("average_final_candidate_quality", 4.05, 4),
        ("average_comparable_revision_improvement", 0.4, 2),
        ("average_revision_count", 0.6, 5),
        ("average_logical_calls", 3.4, 5),
        ("average_latency_seconds", 0.34, 5),
    ):
        assert metrics[key] == {"value": pytest.approx(value), "denominator": denominator}
    empty = evaluate.aggregate([])
    assert empty["average_initial_quality"] == {"value": None, "denominator": 0}
    assert empty["initial_judge_safety_pass_rate"] == {"value": None, "numerator": 0, "denominator": 0}


def test_individual_errors_do_not_abort_run_or_expose_provider_text() -> None:
    agent = Mock()
    agent.run_agent.side_effect = [
        LLMClientError(PRIVATE_PROVIDER_DETAIL),
        JudgeEvaluationError(PRIVATE_PROVIDER_DETAIL),
        result(assessment(4.5), accepted=True, reason=TerminationReason.ACCEPTED),
    ]

    rows = evaluate.run_cases(agent, CASES, max_calls=9)

    assert agent.run_agent.call_args_list == [call(case.request, case.age) for case in CASES]
    assert [row.outcome for row in rows] == ["evaluation_error", "evaluation_error", "first_pass_accepted"]
    assert [row.error for row in rows] == ["LLMClientError", "JudgeEvaluationError", None]
    assert all(row.revision_count is None for row in rows[:2])
    assert PRIVATE_PROVIDER_DETAIL not in repr(rows)


def sdk_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(stop_reason="end_turn", content=[TextBlock(type="text", text=text)])


def valid_verdict(score: int = 5) -> str:
    return json.dumps(
        {
            "safety_pass": True, "scores": dict.fromkeys(JUDGE_WEIGHTS, score),
            "strengths": [], "feedback": [], "safety_issues": [],
        }
    )


@pytest.mark.parametrize(
    ("limit", "responses", "stopped_case"),
    [
        (1, [sdk_response("Draft")], "first"),
        (2, [sdk_response("Draft"), sdk_response("Bad judge JSON")], "first"),
        (3, [sdk_response("Draft"), sdk_response(valid_verdict()), sdk_response("Second draft")], "second"),
    ],
)
def test_shared_budget_prevents_extra_calls_and_judge_corrections(
    limit: int, responses: list[SimpleNamespace], stopped_case: str,
) -> None:
    sdk = Mock(spec=anthropic.Anthropic)
    sdk.messages.create.side_effect = responses
    client = LLMClient(sdk)
    agent = AgentOrchestrator(Storyteller(client), StoryJudge(client))

    rows = evaluate.run_cases(agent, CASES, max_calls=limit)

    assert sdk.messages.create.call_count == limit == sum(row.logical_calls for row in rows)
    assert rows[-1].case_id == stopped_case
    assert rows[-1].outcome == "budget_exhausted" and rows[-1].error is None
    assert rows[-1].used_fallback and rows[-1].delivered_evaluation is None
    if stopped_case == "second":
        assert rows[0].outcome == "first_pass_accepted"


def test_budget_exhausted_before_refinement_preserves_initial_assessment() -> None:
    sdk = Mock(spec=anthropic.Anthropic)
    sdk.messages.create.side_effect = [sdk_response("Draft"), sdk_response(valid_verdict(4))]
    client = LLMClient(sdk)

    rows = evaluate.run_cases(AgentOrchestrator(Storyteller(client), StoryJudge(client)), CASES, max_calls=2)

    assert len(rows) == 1
    assert rows[0].initial_candidate is rows[0].final_candidate
    assert rows[0].initial_candidate is not None and rows[0].initial_candidate.overall_score == 4
    assert rows[0].revision_count == 0 and rows[0].comparison is None
    assert not rows[0].revision_attempted
    assert rows[0].outcome == "budget_exhausted"
    assert sdk.messages.create.call_count == 2


def test_exact_case_boundary_stops_without_starting_next_case() -> None:
    sdk = Mock(spec=anthropic.Anthropic)
    sdk.messages.create.side_effect = [sdk_response("Draft"), sdk_response(valid_verdict())]
    client = LLMClient(sdk)
    agent = AgentOrchestrator(Storyteller(client), StoryJudge(client))

    rows = evaluate.run_cases(agent, CASES, max_calls=2)

    assert len(rows) == 1 and rows[0].accepted
    assert sdk.messages.create.call_count == 2


def test_adapter_budget_exception_is_graceful() -> None:
    agent = Mock()
    agent.run_agent.side_effect = ModelCallBudgetExceeded
    rows = evaluate.run_cases(agent, CASES, max_calls=6)

    assert len(rows) == 1 and rows[0].outcome == "budget_exhausted"
    assert rows[0].logical_calls == 0 and not rows[0].used_fallback
    agent.run_agent.assert_called_once()


def test_writes_three_reports_without_story_or_raw_error_text(tmp_path: Path) -> None:
    row = evaluate.collect_result(
        replace(CASES[0], request=PRIVATE_PROVIDER_DETAIL),
        result(assessment(3.8, safety=False), assessment(3.6), revisions=2, calls=6),
    )
    evaluate.write_reports(tmp_path, "claude-haiku-5-5", CASES, [row], max_calls=6)

    for name in evaluate.REPORT_NAMES:
        contents = (tmp_path / name).read_text()
        assert REJECTED_STORY not in contents
        assert PRIVATE_PROVIDER_DETAIL not in contents
    payload = json.loads((tmp_path / "results.json").read_text())
    assert payload["not_run_case_ids"] == ["second", "third"]
    assert payload["results"][0]["delivered_evaluation"] is None
    assert payload["results"][0]["comparison"]["safety_improved"] is True
    with (tmp_path / "results.csv").open(newline="") as handle:
        csv_row = next(csv.DictReader(handle))
    assert json.loads(csv_row["initial_candidate"])["safety_pass"] is False
    assert json.loads(csv_row["comparison"])["quality_change"] == pytest.approx(-0.2)
    assert csv_row["delivered_evaluation"] == ""
    markdown = (tmp_path / "REPORT.md").read_text()
    assert "Skipped at the call budget: second, third." in markdown
    assert "Initial judge safety pass rate: 0.0% (0/1)" in markdown
    assert "SDK retries and token usage were not measured" in markdown


def test_cli_preview_never_initializes_client_or_writes_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    client_factory = Mock(side_effect=AssertionError("Unexpected live evaluation"))
    monkeypatch.setattr(evaluate, "LLMClient", client_factory)
    output = tmp_path / "not-created"
    assert evaluate.main(["--case", "alice-and-bob", "--output-dir", str(output)]) == 0
    assert "alice-and-bob | age 7" in capsys.readouterr().out
    client_factory.assert_not_called()
    assert not output.exists()


def test_cli_live_wires_the_agents_and_writes_measured_results_with_mocked_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    sdk = Mock(spec=anthropic.Anthropic)
    sdk.messages.create.side_effect = [sdk_response("Draft"), sdk_response(valid_verdict())]
    monkeypatch.setattr(evaluate, "LLMClient", lambda: LLMClient(sdk))
    args = ["--live", "--case", "alice-and-bob", "--max-calls", "2", "--output-dir", str(tmp_path)]

    assert evaluate.main(args) == 0
    assert "Measured 1/1 cases using 2/2 logical calls." in capsys.readouterr().out
    assert sdk.messages.create.call_count == 2
    assert (tmp_path / "results.json").is_file()

    with pytest.raises(SystemExit) as caught:
        evaluate.main(args)
    assert caught.value.code == 2
    assert sdk.messages.create.call_count == 2
