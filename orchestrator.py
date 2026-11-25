"""Bounded story generation, evaluation, and release decisions."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from math import isclose, ulp
from time import perf_counter

from config import (
    JUDGE_WEIGHTS,
    MAX_STORY_REVISIONS,
    MIN_AGE_APPROPRIATENESS_SCORE,
    MIN_BEDTIME_SUITABILITY_SCORE,
    MIN_CRITERION_SCORE,
    MIN_OVERALL_SCORE,
)
from judge import JudgeEvaluation, JudgeEvaluationError, StoryJudge
from llm_client import LLMClientError, ModelCallBudgetExceeded, track_model_calls
from storyteller import Storyteller
from validation import validate_story_request, validate_target_age

FALLBACK_STORY = """\
The Last Little Lantern

As the sky turned lavender, a rabbit named Pip set three paper lanterns on her
windowsill. Two glowed like warm cups of tea. The smallest had a crease that
made its light spill sideways.

Pip reached to straighten it, then saw a little patch of gold on the garden wall.
A moth settled there, folding its wings. Pip left the crease just as it was.

When the moth floated away, Pip tucked the lanterns into their box and climbed
into bed. Outside, the moon left its own patch of light on the wall. Pip watched
it for a while, warm under her quilt, until her eyes gently closed."""


class ProgressEvent(StrEnum):
    """An orchestration stage about to run."""

    GENERATING = "generating"
    EVALUATING = "evaluating"
    REVISING = "revising"
    REEVALUATING = "reevaluating"


class TerminationReason(StrEnum):
    """Why the agent stopped, without including story or provider text."""

    ACCEPTED = "accepted"
    REVISION_LIMIT = "revision_limit"
    GENERATION_ERROR = "generation_error"
    REFINEMENT_ERROR = "refinement_error"
    INVALID_EVALUATION = "invalid_evaluation"
    EVALUATION_ERROR = "evaluation_error"
    CALL_BUDGET_EXHAUSTED = "call_budget_exhausted"


@dataclass(frozen=True)
class CandidateAssessment:
    """Score and decision record for a candidate, without raw model text."""

    scores: dict[str, int]
    overall_score: float
    safety_pass: bool
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True)
class AgentResult:
    """Delivered story and execution metadata for CLI and evaluation callers."""

    story: str
    accepted: bool
    used_fallback: bool
    final_candidate_evaluation: CandidateAssessment | None
    evaluation_history: tuple[CandidateAssessment, ...]
    revision_count: int
    generation_attempts: int
    evaluation_attempts: int
    logical_model_calls: int
    latency_seconds: float
    termination_reason: TerminationReason

    @property
    def initial_evaluation(self) -> CandidateAssessment | None:
        """Return the initial draft's assessment if one was obtained."""
        return self.evaluation_history[0] if self.evaluation_history else None

    @property
    def delivered_evaluation(self) -> CandidateAssessment | None:
        """Return the delivered story's evaluation only for an accepted draft."""
        return self.final_candidate_evaluation if self.accepted else None


def _assess(evaluation: JudgeEvaluation) -> CandidateAssessment:
    """Apply the configured release thresholds to a validated verdict."""
    reasons: list[str] = []
    safety_pass = evaluation.safety_pass is True and not evaluation.safety_issues
    if not safety_pass:
        reasons.append("child_safety")
    overall = evaluation.overall_score
    # Allow only roundoff of a few representable floats at the exact boundary.
    at_boundary = isclose(
        overall, MIN_OVERALL_SCORE, rel_tol=0.0, abs_tol=4 * ulp(MIN_OVERALL_SCORE)
    )
    if not (overall >= MIN_OVERALL_SCORE or at_boundary):
        reasons.append("overall_score")
    specific_minimums = {
        "age_appropriateness": MIN_AGE_APPROPRIATENESS_SCORE,
        "bedtime_suitability": MIN_BEDTIME_SUITABILITY_SCORE,
    }
    for criterion, score in evaluation.scores.items():
        minimum = specific_minimums.get(criterion, MIN_CRITERION_SCORE)
        if score < minimum:
            reasons.append(criterion)
    return CandidateAssessment(
        evaluation.scores.copy(), overall, safety_pass, tuple(reasons)
    )


def _revision_feedback(evaluation: JudgeEvaluation, assessment: CandidateAssessment) -> str:
    """Carry judge suggestions and safety concerns through the existing text interface."""
    parts = [f"Improvement: {suggestion}" for suggestion in evaluation.feedback]
    parts.extend(
        f"Safety concern to remove or safely replace: {issue}" for issue in evaluation.safety_issues
    )
    targets = set(assessment.rejection_reasons) & evaluation.scores.keys()
    if "overall_score" in assessment.rejection_reasons:
        lowest_score = min(evaluation.scores.values())
        targets.update(key for key, score in evaluation.scores.items() if score == lowest_score)
    if targets:
        parts.append("Improve these rubric areas: " + ", ".join(sorted(targets)) + ".")
    return "\n".join(parts)


class AgentOrchestrator:
    """Coordinate injected storyteller and judge agents without routing calls."""

    def __init__(self, storyteller: Storyteller, judge: StoryJudge) -> None:
        self._storyteller = storyteller
        self._judge = judge

    def run_agent(
        self,
        request: str,
        age: int,
        *,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> AgentResult:
        """Return the first candidate that passes or a prewritten fallback."""
        validate_story_request(request)
        validate_target_age(age)

        start = perf_counter()
        history: list[CandidateAssessment] = []
        final_assessment = None
        generation_attempts = evaluation_attempts = revision_count = 0
        reason = TerminationReason.REVISION_LIMIT
        candidate = feedback = ""

        with track_model_calls() as calls:
            for revision in range(MAX_STORY_REVISIONS + 1):
                generation_attempts += 1
                if on_progress is not None:
                    on_progress(ProgressEvent.REVISING if revision else ProgressEvent.GENERATING)
                try:
                    if revision == 0:
                        candidate = self._storyteller.generate_story(request, age)
                    else:
                        candidate = self._storyteller.revise_story(request, age, candidate, feedback)
                except ModelCallBudgetExceeded:
                    generation_attempts -= 1
                    reason = TerminationReason.CALL_BUDGET_EXHAUSTED
                    break
                except LLMClientError:
                    reason = (
                        TerminationReason.REFINEMENT_ERROR
                        if revision
                        else TerminationReason.GENERATION_ERROR
                    )
                    break

                revision_count = revision
                final_assessment = None
                evaluation_attempts += 1
                if on_progress is not None:
                    on_progress(
                        ProgressEvent.REEVALUATING if revision else ProgressEvent.EVALUATING
                    )
                try:
                    evaluation = self._judge.evaluate_story(request, age, candidate)
                except ModelCallBudgetExceeded:
                    reason = TerminationReason.CALL_BUDGET_EXHAUSTED
                    break
                except JudgeEvaluationError:
                    reason = TerminationReason.INVALID_EVALUATION
                    break
                except LLMClientError:
                    reason = TerminationReason.EVALUATION_ERROR
                    break

                if (
                    not isinstance(evaluation, JudgeEvaluation)
                    or evaluation.scores.keys() != JUDGE_WEIGHTS.keys()
                ):
                    reason = TerminationReason.INVALID_EVALUATION
                    break
                final_assessment = _assess(evaluation)
                history.append(final_assessment)
                if not final_assessment.rejection_reasons:
                    reason = TerminationReason.ACCEPTED
                    break
                if revision < MAX_STORY_REVISIONS:
                    feedback = _revision_feedback(evaluation, final_assessment)

        accepted = reason is TerminationReason.ACCEPTED
        return AgentResult(
            story=candidate if accepted else FALLBACK_STORY,
            accepted=accepted,
            used_fallback=not accepted,
            final_candidate_evaluation=final_assessment,
            evaluation_history=tuple(history),
            revision_count=revision_count,
            generation_attempts=generation_attempts,
            evaluation_attempts=evaluation_attempts,
            logical_model_calls=calls.count,
            latency_seconds=perf_counter() - start,
            termination_reason=reason,
        )
