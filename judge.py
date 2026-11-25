"""Evaluate bedtime story drafts with a validated, structured LLM verdict."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from math import inf

from config import JUDGE_FEEDBACK_SCORE_THRESHOLD, JUDGE_WEIGHTS
from llm_client import LLMClient
from prompts import story_judge_prompts

_STRING_LIST = {"type": "array", "items": {"type": "string"}}
_EVALUATION_PROPERTIES = {
    "safety_pass": {"type": "boolean"},
    "scores": {
        "type": "object",
        "properties": {criterion: {"type": "integer"} for criterion in JUDGE_WEIGHTS},
        "required": list(JUDGE_WEIGHTS),
        "additionalProperties": False,
    },
    "strengths": _STRING_LIST,
    "feedback": _STRING_LIST,
    "safety_issues": _STRING_LIST,
}
_EVALUATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": _EVALUATION_PROPERTIES,
    "required": list(_EVALUATION_PROPERTIES),
    "additionalProperties": False,
}


class JudgeEvaluationError(RuntimeError):
    """The judge could not provide a valid evaluation."""


@dataclass(frozen=True)
class JudgeEvaluation:
    """Validated rubric scores, feedback, and an independent child-safety verdict."""

    safety_pass: bool
    scores: dict[str, int]
    overall_score: float
    strengths: list[str]
    feedback: list[str]
    safety_issues: list[str]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys, including a repeated safety verdict."""
    result = dict(pairs)
    if len(result) != len(pairs):
        raise JudgeEvaluationError("The judge returned duplicate JSON fields.")
    return result


def _string_list(value: object, field: str) -> list[str]:
    """Require a list of non-blank strings and trim each entry."""
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise JudgeEvaluationError(f"The judge's {field} must be a list of non-blank strings.")
    return [item.strip() for item in value]


def _parse_evaluation(response: str, weights: Mapping[str, float]) -> JudgeEvaluation:
    """Validate the JSON response and calculate its weighted mean on the 1–5 scale."""
    try:
        data = json.loads(response, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        raise JudgeEvaluationError("The judge did not return valid JSON.") from None
    if not isinstance(data, dict) or data.keys() != _EVALUATION_PROPERTIES.keys():
        raise JudgeEvaluationError("The judge returned incorrect evaluation fields.")

    safety_pass = data["safety_pass"]
    if type(safety_pass) is not bool:
        raise JudgeEvaluationError("The judge's safety verdict must be a boolean.")

    scores = data["scores"]
    if not isinstance(scores, dict) or scores.keys() != weights.keys():
        raise JudgeEvaluationError("The judge returned incorrect score fields.")
    if any(type(score) is not int or not 1 <= score <= 5 for score in scores.values()):
        raise JudgeEvaluationError("Every judge score must be an integer from 1 to 5.")

    strengths = _string_list(data["strengths"], "strengths")
    feedback = _string_list(data["feedback"], "feedback")
    safety_issues = _string_list(data["safety_issues"], "safety issues")
    if safety_pass == bool(safety_issues):
        raise JudgeEvaluationError("The judge's safety verdict and issues contradict each other.")
    if not feedback and (not safety_pass or min(scores.values()) <= JUDGE_FEEDBACK_SCORE_THRESHOLD):
        raise JudgeEvaluationError("The judge must provide feedback for weaknesses or safety issues.")

    weighted_total = sum(scores[key] * weight for key, weight in weights.items())
    overall_score = weighted_total / sum(weights.values())
    return JudgeEvaluation(safety_pass, scores, overall_score, strengths, feedback, safety_issues)


class StoryJudge:
    """Request an independent story evaluation through the shared client."""

    def __init__(self, client: LLMClient, *, weights: Mapping[str, float] = JUDGE_WEIGHTS) -> None:
        """Use the configured default weights or a complete set of positive relative weights."""
        if weights.keys() != JUDGE_WEIGHTS.keys() or any(
            type(weight) not in (int, float) or not 0 < weight < inf for weight in weights.values()
        ):
            raise ValueError("Judge weights must be positive and finite for all five criteria.")
        self._client = client
        largest_weight = max(weights.values())
        self._weights = {key: weights[key] / largest_weight for key in JUDGE_WEIGHTS}

    def evaluate_story(self, request: str, age: int, story: str) -> JudgeEvaluation:
        """Evaluate a draft, allowing one correction for an invalid verdict."""
        if not isinstance(request, str) or not request.strip():
            raise ValueError("Story request must be non-empty text.")
        if type(age) is not int or not 5 <= age <= 10:
            raise ValueError("Age must be an integer from 5 to 10.")
        if not isinstance(story, str) or not story.strip():
            raise ValueError("Story must be non-empty text.")

        for correction in (False, True):
            system_prompt, user_message = story_judge_prompts(
                request, age, story, correction=correction
            )
            response = self._client.generate_text(
                system_prompt=system_prompt, user_message=user_message, json_schema=_EVALUATION_SCHEMA
            )
            try:
                return _parse_evaluation(response, self._weights)
            except JudgeEvaluationError:
                continue
        raise JudgeEvaluationError("The judge returned an invalid evaluation after one correction attempt.")
