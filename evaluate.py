"""Run and report a bounded live evaluation of the existing bedtime story agent."""

import argparse
import csv
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Protocol

from judge import JudgeEvaluationError, StoryJudge
from llm_client import LLMClient, LLMClientError, ModelCallBudgetExceeded, track_model_calls
from orchestrator import AgentOrchestrator, AgentResult, CandidateAssessment, TerminationReason
from storyteller import Storyteller
from validation import validate_story_request, validate_target_age

EVALUATIONS_DIR = Path(__file__).with_name("evaluations")
DEFAULT_DATASET = EVALUATIONS_DIR / "cases.json"
DEFAULT_CALL_BUDGET = 30
REPORT_NAMES = ("results.json", "results.csv", "REPORT.md")
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_ERROR_REASONS = {
    TerminationReason.GENERATION_ERROR,
    TerminationReason.REFINEMENT_ERROR,
    TerminationReason.EVALUATION_ERROR,
    TerminationReason.INVALID_EVALUATION,
    TerminationReason.WORKFLOW_DEADLINE_EXCEEDED,
}


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    request: str
    age: int
    category: str
    expected_behavior: str


@dataclass(frozen=True)
class CandidateComparison:
    quality_change: float
    criterion_changes: dict[str, int]
    safety_improved: bool
    safety_regressed: bool


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    age: int
    category: str
    initial_candidate: CandidateAssessment | None
    final_candidate: CandidateAssessment | None
    delivered_evaluation: CandidateAssessment | None
    comparison: CandidateComparison | None
    revision_count: int | None
    revision_attempted: bool | None
    logical_calls: int
    latency_seconds: float
    accepted: bool
    used_fallback: bool
    termination_reason: str
    outcome: str
    error: str | None


class EvaluationAgent(Protocol):
    def run_agent(self, request: str, age: int) -> AgentResult: ...


def load_cases(path: Path) -> list[EvaluationCase]:
    """Validate the dataset before initializing the model client."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        raise ValueError("Could not read a valid evaluation dataset.") from None
    if not isinstance(rows, list) or not rows:
        raise ValueError("The evaluation dataset must be a nonempty JSON array.")

    fields = {"id", "request", "age", "category", "expected_behavior"}
    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        try:
            if not isinstance(row, dict) or row.keys() != fields:
                raise ValueError
            case_id, category, expected = row["id"], row["category"], row["expected_behavior"]
            if not all(isinstance(value, str) and _SLUG.fullmatch(value) for value in (case_id, category)):
                raise ValueError
            if not isinstance(expected, str) or not expected.strip() or case_id in seen:
                raise ValueError
            validate_story_request(row["request"])
            validate_target_age(row["age"])
        except ValueError:
            raise ValueError(f"Invalid evaluation case at row {index}.") from None
        cases.append(EvaluationCase(case_id, row["request"], row["age"], category, expected))
        seen.add(case_id)
    return cases


def select_cases(cases: Sequence[EvaluationCase], ids: Sequence[str]) -> list[EvaluationCase]:
    """Select case IDs in dataset order."""
    if set(ids) - {case.case_id for case in cases}:
        raise ValueError("One or more selected case IDs are not in the dataset.")
    return [case for case in cases if not ids or case.case_id in ids]


def collect_result(case: EvaluationCase, result: AgentResult) -> CaseResult:
    """Collect only score and workflow metadata from a completed case."""
    initial = result.initial_evaluation
    final = result.final_candidate_evaluation
    comparison = None
    if result.revision_count and initial is not None and final is not None:
        comparison = CandidateComparison(
            quality_change=final.overall_score - initial.overall_score,
            criterion_changes={key: final.scores[key] - score for key, score in initial.scores.items()},
            safety_improved=not initial.safety_pass and final.safety_pass,
            safety_regressed=initial.safety_pass and not final.safety_pass,
        )

    reason = result.termination_reason
    attempted = result.generation_attempts > 1
    error = reason.value if reason in _ERROR_REASONS else None
    if error:
        outcome = "evaluation_error"
    elif reason is TerminationReason.CALL_BUDGET_EXHAUSTED:
        outcome = "budget_exhausted"
    elif result.accepted:
        outcome = "refined_accepted" if result.revision_count else "first_pass_accepted"
    else:
        outcome = "unsuccessful_refinement" if attempted else "fallback"

    return CaseResult(
        case.case_id, case.age, case.category, initial, final, result.delivered_evaluation,
        comparison, result.revision_count, attempted, result.logical_model_calls,
        result.latency_seconds, result.accepted, result.used_fallback, reason.value, outcome, error,
    )


def run_cases(
    agent: EvaluationAgent, cases: Sequence[EvaluationCase], *, max_calls: int
) -> list[CaseResult]:
    """Run sequentially with a shared limit checked before each logical SDK call."""
    results: list[CaseResult] = []
    with track_model_calls(limit=max_calls) as budget:
        for case in cases:
            if budget.count >= max_calls:
                break
            start = perf_counter()
            before = budget.count
            try:
                result = collect_result(case, agent.run_agent(case.request, case.age))
            except (LLMClientError, JudgeEvaluationError, ModelCallBudgetExceeded) as error:
                # Defensive handling for adapters that surface errors instead of AgentResult.
                exhausted = isinstance(error, ModelCallBudgetExceeded)
                code = "call_budget_exhausted" if exhausted else type(error).__name__
                result = CaseResult(
                    case.case_id, case.age, case.category, None, None, None, None, None, None,
                    budget.count - before, perf_counter() - start, False, False, code,
                    "budget_exhausted" if exhausted else "evaluation_error",
                    None if exhausted else code,
                )
            results.append(result)
            if result.outcome == "budget_exhausted":
                break
    return results


def _average(values: list[int] | list[float]) -> dict[str, int | float | None]:
    return {"value": mean(values) if values else None, "denominator": len(values)}


def _rate(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def aggregate(results: Sequence[CaseResult]) -> dict[str, object]:
    """Calculate metrics over started cases and available measurements."""
    total = len(results)
    initial = [row.initial_candidate for row in results if row.initial_candidate is not None]
    final = [row.final_candidate for row in results if row.final_candidate is not None]
    revised = [row for row in results if row.revision_attempted]
    comparisons = [row.comparison for row in results if row.comparison is not None]
    return {
        "total_evaluation_requests": total,
        "total_logical_calls": sum(row.logical_calls for row in results),
        "average_initial_quality": _average([value.overall_score for value in initial]),
        "average_final_candidate_quality": _average([value.overall_score for value in final]),
        "average_comparable_revision_improvement": _average([value.quality_change for value in comparisons]),
        "first_pass_acceptance_rate": _rate(sum(row.outcome == "first_pass_accepted" for row in results), total),
        "final_generated_acceptance_rate": _rate(sum(row.accepted for row in results), total),
        "revision_success_rate": _rate(sum(row.accepted for row in revised), len(revised)),
        "initial_judge_safety_pass_rate": _rate(sum(value.safety_pass for value in initial), len(initial)),
        "final_judge_safety_pass_rate": _rate(sum(value.safety_pass for value in final), len(final)),
        "fallback_rate": _rate(sum(row.used_fallback for row in results), total),
        "average_revision_count": _average([row.revision_count for row in results if row.revision_count is not None]),
        "average_logical_calls": _average([row.logical_calls for row in results]),
        "average_latency_seconds": _average([row.latency_seconds for row in results]),
        "evaluation_error_rate": _rate(sum(row.error is not None for row in results), total),
    }


def _case_csv_row(result: CaseResult) -> dict[str, object]:
    row = asdict(result)
    for key in ("initial_candidate", "final_candidate", "delivered_evaluation", "comparison"):
        row[key] = json.dumps(row[key]) if row[key] is not None else ""
    return row


def _markdown_report(
    model_id: str, selected: Sequence[EvaluationCase], results: Sequence[CaseResult],
    max_calls: int, metrics: dict[str, object],
) -> str:
    not_run = [case.case_id for case in selected[len(results):]]
    lines = [
        "# Live bedtime story evaluation", "", f"Model ID: `{model_id}`.",
        f"Logical request budget: {max_calls}. SDK retries and token usage were not measured.",
        "Generation used the production acceptance and refinement rules. The initial draft is the "
        "baseline, and the final candidate is the last generated draft, when evaluated.",
        "A fallback has no delivered assessment. See the input dataset for prompts and expected behaviors.",
        "", "## Measured cases", "",
        "| Case | Age | Category | Initial quality / safety | Final quality / safety | Change | Revisions | Calls | Seconds | Accepted | Fallback | Outcome | Termination |",
        "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]

    def score_and_safety(value: CandidateAssessment | None) -> str:
        if value is None:
            return "Unmeasured"
        return f"{value.overall_score:.2f} / {'pass' if value.safety_pass else 'fail'}"

    for row in results:
        change = f"{row.comparison.quality_change:+.2f}" if row.comparison else "—"
        revisions = row.revision_count if row.revision_count is not None else "—"
        lines.append(
            f"| {row.case_id} | {row.age} | {row.category} | {score_and_safety(row.initial_candidate)} | "
            f"{score_and_safety(row.final_candidate)} | {change} | {revisions} | {row.logical_calls} | "
            f"{row.latency_seconds:.2f} | {'Yes' if row.accepted else 'No'} | "
            f"{'Yes' if row.used_fallback else 'No'} | {row.outcome} | {row.termination_reason} |"
        )
    lines.extend(["", "Case criterion scores and paired criterion changes are in the JSON and CSV reports."])
    if not_run:
        lines.extend(["", f"Skipped at the call budget: {', '.join(not_run)}."])
    lines.extend(["", "## Aggregate metrics", ""])
    for name, metric in metrics.items():
        label = name.replace("_", " ").capitalize()
        if not isinstance(metric, dict):
            lines.append(f"- {label}: {metric}")
        elif "numerator" in metric:
            rate = f"{metric['value']:.1%}" if metric["value"] is not None else "Unavailable"
            lines.append(f"- {label}: {rate} ({metric['numerator']}/{metric['denominator']})")
        else:
            average = f"{metric['value']:.3f}" if metric["value"] is not None else "Unavailable"
            lines.append(f"- {label}: {average} (n={metric['denominator']})")
    lines.extend([
        "", "## Observed review flags", "",
        f"- Fallbacks: {sum(row.used_fallback for row in results)}",
        f"- Evaluation errors: {sum(row.error is not None for row in results)}",
        f"- Comparable revisions with no quality gain: "
        f"{sum(row.comparison is not None and row.comparison.quality_change <= 0 for row in results)}",
        f"- Judge-reported safety regressions: "
        f"{sum(row.comparison is not None and row.comparison.safety_regressed for row in results)}",
        "", "## Limitations and follow-up", "",
        "Review flagged cases individually. "
        "Check whether lower alignment scores fairly account for safe adaptations.",
        "The same model generates and evaluates, so mistakes can be correlated. Structured "
        "validation checks response shape, scores may vary, and this small dataset cannot "
        "establish child safety or comprehensive protection from prompt injection.",
        "Use the manual review checklist in evaluations/README.md before interpreting judge "
        "scores as evidence of improvement.", "",
    ])
    return "\n".join(lines)


def write_reports(
    output_dir: Path, model_id: str, selected: Sequence[EvaluationCase],
    results: Sequence[CaseResult], *, max_calls: int,
) -> None:
    """Write measured results without including story, prompt, or provider error text."""
    if not results:
        raise ValueError("There are no measured evaluation cases to report.")
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = aggregate(results)
    payload = {
        "mode": "live",
        "model": model_id,
        "max_logical_calls": max_calls,
        "selected_case_ids": [case.case_id for case in selected],
        "not_run_case_ids": [case.case_id for case in selected[len(results):]],
        "sdk_retries_measured": False,
        "metrics": metrics,
        "results": [asdict(row) for row in results],
    }
    json_path, csv_path, md_path = (output_dir / name for name in REPORT_NAMES)
    with json_path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
    with csv_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_case_csv_row(results[0])))
        writer.writeheader()
        writer.writerows(_case_csv_row(row) for row in results)
    with md_path.open("x", encoding="utf-8") as handle:
        handle.write(_markdown_report(model_id, selected, results, max_calls, metrics))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--case", action="append", default=[], help="Select a case ID; repeat to select more.")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_CALL_BUDGET)
    parser.add_argument("--output-dir", type=Path, default=EVALUATIONS_DIR)
    parser.add_argument("--live", action="store_true", help="Run live API requests and write measured reports.")
    args = parser.parse_args(argv)

    try:
        selected = select_cases(load_cases(args.dataset), args.case)
        if args.max_calls <= 0:
            raise ValueError("--max-calls must be positive.")
    except ValueError as error:
        parser.error(str(error))

    if not args.live:
        for case in selected:
            print(f"{case.case_id} | age {case.age} | {case.category}")
        print("Preview only. Use --live to run the selected cases.")
        return 0

    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if any((args.output_dir / name).exists() or (args.output_dir / name).is_symlink()
               for name in REPORT_NAMES):
            parser.error("Report files already exist. Choose a new --output-dir.")
        client = LLMClient()
        agent = AgentOrchestrator(Storyteller(client), StoryJudge(client))
        results = run_cases(agent, selected, max_calls=args.max_calls)
        write_reports(args.output_dir, client.model_id, selected, results, max_calls=args.max_calls)
    except LLMClientError:
        print("Could not initialize the configured story service.", file=sys.stderr)
        return 1
    except OSError:
        print("Could not write the evaluation reports.", file=sys.stderr)
        return 1

    total_calls = sum(row.logical_calls for row in results)
    print(f"Measured {len(results)}/{len(selected)} cases using {total_calls}/{args.max_calls} logical calls.")
    if len(results) < len(selected) or any(row.outcome == "budget_exhausted" for row in results):
        print("Stopped at the logical call budget. Reports contain the measurements available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
