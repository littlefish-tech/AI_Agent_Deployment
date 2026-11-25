"""Generate and revise internal bedtime story drafts."""

from llm_client import LLMClient, LLMClientError
from prompts import story_generation_prompts, story_refinement_prompts


class Storyteller:
    """Prepare story requests for an injected shared LLM client."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def generate_story(self, request: str, age: int) -> str:
        """Generate an initial draft for the given request and age."""
        self._validate_request(request, age)
        return self._generate(*story_generation_prompts(request, age))

    def revise_story(
        self, request: str, age: int, original_story: str, judge_feedback: str
    ) -> str:
        """Return a complete revised draft based on the request and feedback."""
        self._validate_request(request, age)
        if not isinstance(original_story, str) or not original_story.strip():
            raise ValueError("Original story must be non-empty text.")
        if not isinstance(judge_feedback, str) or not judge_feedback.strip():
            raise ValueError("Judge feedback must be non-empty text.")
        return self._generate(*story_refinement_prompts(request, age, original_story, judge_feedback))

    @staticmethod
    def _validate_request(request: str, age: int) -> None:
        """Check inputs before constructing a prompt or calling the model."""
        if not isinstance(request, str) or not request.strip():
            raise ValueError("Story request must be non-empty text.")
        if type(age) is not int or not 5 <= age <= 10:
            raise ValueError("Age must be an integer from 5 to 10.")

    def _generate(self, system_prompt: str, user_message: str) -> str:
        """Use the shared client's configured defaults and require usable text."""
        story = self._client.generate_text(system_prompt=system_prompt, user_message=user_message)
        if not story.strip():
            raise LLMClientError("The storyteller received an empty draft.")
        return story.strip()
