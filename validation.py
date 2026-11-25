"""Input checks shared by the CLI and orchestration entry point."""

from config import MAX_STORY_AGE, MAX_STORY_REQUEST_LENGTH, MIN_STORY_AGE


def validate_story_request(request: str) -> None:
    """Require non-blank story text within the request length limit."""
    if not isinstance(request, str) or not request.strip():
        raise ValueError("Please enter a bedtime story idea.")
    if len(request) > MAX_STORY_REQUEST_LENGTH:
        raise ValueError(f"Please keep your story idea to {MAX_STORY_REQUEST_LENGTH:,} characters.")


def validate_target_age(age: int) -> None:
    """Require an integer age in the supported range."""
    if type(age) is not int or not MIN_STORY_AGE <= age <= MAX_STORY_AGE:
        raise ValueError(f"Please enter a whole-number age from {MIN_STORY_AGE} to {MAX_STORY_AGE}.")
