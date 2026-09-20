"""Session 1 reference: stream responses while keeping recent context."""

import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def build_instructions() -> str:
    """Define a contract that handles uncertainty explicitly."""
    return """You are a concise and rigorous learning assistant.

Answer in clear Portuguese. When essential information is missing, do not
invent it; say what you do not know and suggest a useful next step or ask one
focused question.
"""


def build_input(question: str, history: list[dict[str, str]]) -> str:
    """Include only the two most recent full turns of the conversation."""
    recent_history = history[-4:]
    context_lines = [
        f"{turn['role'].upper()}: {turn['content']}" for turn in recent_history
    ]
    conversation_context = "\n".join(context_lines) or "(no previous context)"
    return (
        "Recent conversation context:\n"
        f"{conversation_context}\n\n"
        "New user question:\n"
        f"{question}"
    )


def stream_answer(question: str, history: list[dict[str, str]]) -> str:
    """Print one answer progressively and return its complete text."""
    client = OpenAI()
    stream = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        instructions=build_instructions(),
        input=build_input(question, history),
        stream=True,
    )

    answer_parts: list[str] = []
    for event in stream:
        if event.type == "response.output_text.delta":
            answer_parts.append(event.delta)
            print(event.delta, end="", flush=True)

    print()
    return "".join(answer_parts)


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")

    history: list[dict[str, str]] = []
    print("Ask a question. Use /reset to clear context or /quit to exit.")

    while True:
        question = input("\nYou: ").strip()
        if question == "/quit":
            break
        if question == "/reset":
            history.clear()
            print("Conversation context cleared.")
            continue
        if not question:
            print("Please enter a question.")
            continue

        print("\nAssistant: ", end="")
        answer = stream_answer(question, history)
        history.extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ])


if __name__ == "__main__":
    main()
