"""Which model runs the agents: the course OpenAI configuration, read from the environment or .env."""

import os

from dotenv import load_dotenv

DEFAULT_MODEL = "gpt-4.1-mini"
# Limits shared by the whole team in one investigation.
REQUEST_TIMEOUT_SECONDS = 30
INVESTIGATION_TIMEOUT_SECONDS = 120
MAX_MODEL_REQUESTS = 40
MAX_TOOL_CALLS = 80


def configured_model() -> str:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY não está configurada. Os agentes não foram iniciados.")
    return f"openai:{os.getenv('OPENAI_MODEL', DEFAULT_MODEL)}"
