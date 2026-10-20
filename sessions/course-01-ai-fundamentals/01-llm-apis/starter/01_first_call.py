"""Session 1 baseline: a complete, minimal question-answer application."""

import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")

INSTRUCTIONS = """You are a concise learning assistant.
Explain concepts in clear Portuguese. If a question is ambiguous, ask one
focused follow-up question instead of making an unsupported assumption.
"""


def answer_question(question: str) -> str:
    """Return one useful answer for one learner question."""
    client = OpenAI()
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        instructions=INSTRUCTIONS,
        input=question,
    )
    return response.output_text


def main() -> None:
    question = input("Ask a learning question: ").strip()
    if not question:
        raise ValueError("Please enter a question.")

    print(f"\n{answer_question(question)}")


if __name__ == "__main__":
    main()
