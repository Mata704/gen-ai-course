"""Use the course's OpenAI configuration without storing credentials."""

import os

from dotenv import load_dotenv


def configured_model() -> str:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY não está configurada. Os agentes não foram iniciados.")
    return f"openai:{os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')}"
