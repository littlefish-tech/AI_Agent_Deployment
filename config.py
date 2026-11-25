"""Configuration for the shared Claude client."""

import os
from pathlib import Path
from typing import Final

from dotenv import dotenv_values

MODEL_ID: Final = "claude-haiku-5-5"
DEFAULT_MAX_OUTPUT_TOKENS: Final = 4_096
REQUEST_TIMEOUT_SECONDS: Final = 30.0
MAX_RETRIES: Final = 2
DOTENV_PATH: Final = Path(__file__).with_name(".env")


def get_anthropic_api_key() -> str | None:
    """Read the environment first, with the project-local .env as a fallback."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key is None:
        api_key = dotenv_values(DOTENV_PATH, interpolate=False).get("ANTHROPIC_API_KEY")
    return (api_key or "").strip() or None
