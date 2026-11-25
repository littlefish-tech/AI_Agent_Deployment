"""Application settings for the Claude client and story evaluation."""

import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from dotenv import dotenv_values

MODEL_ID: Final = "claude-haiku-5-5"
DEFAULT_MAX_OUTPUT_TOKENS: Final = 4_096
REQUEST_TIMEOUT_SECONDS: Final = 30.0
MAX_RETRIES: Final = 2
DOTENV_PATH: Final = Path(__file__).with_name(".env")
JUDGE_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "age_appropriateness": 25,
        "narrative_coherence": 20,
        "creativity": 15,
        "request_alignment": 15,
        "bedtime_suitability": 25,
    }
)
JUDGE_FEEDBACK_SCORE_THRESHOLD: Final = 3
MAX_STORY_REVISIONS: Final = 2
MIN_OVERALL_SCORE: Final = 4.2
MIN_CRITERION_SCORE: Final = 3
MIN_AGE_APPROPRIATENESS_SCORE: Final = 4
MIN_BEDTIME_SUITABILITY_SCORE: Final = 4


def get_anthropic_api_key() -> str | None:
    """Read the environment first, with the project-local .env as a fallback."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key is None:
        api_key = dotenv_values(DOTENV_PATH, interpolate=False).get("ANTHROPIC_API_KEY")
    return (api_key or "").strip() or None
