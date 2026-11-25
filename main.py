"""
Before submitting the assignment, describe here in a few sentences what you would have built next if you spent 2 more hours on this project:

"""

import argparse
import sys
from collections.abc import Sequence

from config import DEFAULT_STORY_AGE, MAX_STORY_AGE, MIN_STORY_AGE, MODEL_ID
from judge import StoryJudge
from llm_client import LLMClient, LLMClientError
from orchestrator import (
    AgentOrchestrator,
    AgentResult,
    CandidateAssessment,
    ProgressEvent,
    TerminationReason,
)
from storyteller import Storyteller
from validation import validate_story_request, validate_target_age

_PROGRESS_MESSAGES = {
    ProgressEvent.GENERATING: "Generating your bedtime story...",
    ProgressEvent.EVALUATING: "Evaluating story quality and age appropriateness...",
    ProgressEvent.REVISING: "Improving the story based on feedback...",
    ProgressEvent.REEVALUATING: "Reevaluating the revised story...",
}
_FALLBACK_REASONS = {
    TerminationReason.GENERATION_ERROR: "The story service could not generate a draft.",
    TerminationReason.REFINEMENT_ERROR: "The story service could not finish revising the draft.",
    TerminationReason.EVALUATION_ERROR: "The story service could not finish its checks.",
    TerminationReason.INVALID_EVALUATION: "The story checks returned an unusable result.",
}


def _read_request() -> str:
    while True:
        request = input("What kind of bedtime story would you like to hear? ").strip()
        try:
            validate_story_request(request)
        except ValueError as error:
            print(error)
        else:
            return request


def _read_age() -> int:
    prompt = f"Target age ({MIN_STORY_AGE}–{MAX_STORY_AGE}, default {DEFAULT_STORY_AGE}): "
    while True:
        raw_age = input(prompt).strip()
        if not raw_age:
            return DEFAULT_STORY_AGE
        try:
            age = int(raw_age)
        except ValueError:
            print("Please enter a whole number for the age.")
            continue
        try:
            validate_target_age(age)
        except ValueError as error:
            print(error)
        else:
            return age


def _report_progress(event: ProgressEvent) -> None:
    print(_PROGRESS_MESSAGES[event], flush=True)


def _print_assessment(label: str, assessment: CandidateAssessment | None) -> None:
    if assessment is None:
        print(f"{label}: evaluation unavailable")
        return
    safety = "passed" if assessment.safety_pass else "failed"
    print(f"{label}: {assessment.overall_score:.2f}/5 (child safety {safety})")
    for criterion, score in assessment.scores.items():
        print(f"  {criterion.replace('_', ' ').capitalize()}: {score}/5")


def _print_debug(result: AgentResult) -> None:
    print("\nExecution details")
    print(f"Model: {MODEL_ID}")
    _print_assessment("Initial candidate quality", result.initial_evaluation)
    _print_assessment("Final candidate quality", result.final_candidate_evaluation)
    if result.used_fallback:
        print("Delivered story: prewritten fallback (no evaluation score)")
    print(f"Accepted: {'yes' if result.accepted else 'no'}")
    print(f"Fallback used: {'yes' if result.used_fallback else 'no'}")
    print(f"Completed revisions: {result.revision_count}")
    print(f"Logical LLM calls: {result.logical_model_calls}")
    print(f"Execution latency: {result.latency_seconds:.2f}s")
    print(f"Termination reason: {result.termination_reason.value}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one interactive story session and return its exit status."""
    parser = argparse.ArgumentParser(description="Create a bedtime story for ages 5–10.")
    parser.add_argument("--debug", action="store_true", help="Show scores and execution details.")
    args = parser.parse_args(argv)

    print("Welcome! Let's make a bedtime story.")
    try:
        try:
            request, age = _read_request(), _read_age()
        except EOFError:
            print("\nGood night!")
            return 0

        try:
            client = LLMClient()
        except LLMClientError:
            print(
                "Could not start the story service. Check that ANTHROPIC_API_KEY "
                "is set in your environment or accessible in your local .env file.",
                file=sys.stderr,
            )
            return 1

        agent = AgentOrchestrator(Storyteller(client), StoryJudge(client))
        result = agent.run_agent(request, age, on_progress=_report_progress)
    except KeyboardInterrupt:
        print("\nStory session cancelled.", file=sys.stderr)
        return 130

    if result.used_fallback:
        reason = _FALLBACK_REASONS.get(result.termination_reason)
        if reason:
            print(reason)
        print(
            "We couldn't create a suitable personalized story. "
            "Here's a prewritten bedtime story instead."
        )
    else:
        print("Your bedtime story is ready!")
    print(f"\n{result.story}")
    if args.debug:
        _print_debug(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
