"""Session 1 extension: stream responses and make context a design choice."""

import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")

def build_instructions() -> str:
    """Return the current assistant contract.

    TODO: improve this contract. Decide how the assistant should respond to
    unclear questions and to information it has not received.

    Hint 1: write the expected behaviour before writing the prompt.
    Hint 2: useful uncertainty names what is missing and proposes one next step.
    """
    return "You are a concise learning assistant. Be helpful and clear."


def build_input(question: str, history: list[dict[str, str]]) -> str:
    """Build the input sent to the model.

    TODO: this baseline ignores history, so the assistant has no memory. Decide
    which previous turns are useful to retain and how many are enough.

    Hint 1: prove the problem with two questions where the second depends on the
    first.
    Hint 2: start with a small recent window rather than every prior turn.
    Hint 3: make the boundary between conversation context and new question
    obvious to the model.
    """
    _ = history
    return question


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

        print("Assistant: ", end="")
        answer = stream_answer(question, history)
        history.extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ])


if __name__ == "__main__":
    main()
