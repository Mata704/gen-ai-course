"""Session 1 challenge: design a responsible terminal learning assistant."""

import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")


def build_instructions() -> str:
    """Define the assistant's behavioural contract.

    TODO: Write instructions that make the assistant useful for learning while
    preventing it from inventing course-specific facts it does not know.

    Hint 1: state the assistant's role and preferred answer style.
    Hint 2: specify what it should do when information is absent or ambiguous.
    Hint 3: make its next step useful to a learner, not merely defensive.
    """
    raise NotImplementedError("Complete build_instructions() before running.")


def build_input(question: str, history: list[dict[str, str]]) -> str:
    """Choose the relevant context for this question.

    TODO: Decide how to include useful history without sending every prior turn
    forever. Start with a small recent-message window.

    Hint 1: first make a single previous turn available.
    Hint 2: expand to a bounded recent window only after the first test passes.
    Hint 3: use labels so the model can distinguish previous messages from the
    learner's new question.
    """
    raise NotImplementedError("Complete build_input() before running.")


def choose_generation_settings(task_type: str) -> dict[str, int | float]:
    """Choose settings appropriate to the task.

    TODO: Return settings for a factual learning answer. Be ready to justify how
    the settings would differ for a creative brainstorming task.

    Hint 1: start with only one setting.
    Hint 2: explain the effect you expect before running the comparison.
    Hint 3: consider consistency, response length, cost, and latency together.
    """
    raise NotImplementedError(
        "Complete choose_generation_settings() before running."
    )


def stream_answer(question: str, history: list[dict[str, str]]) -> str:
    """Stream one answer using the decisions made in the functions above."""
    client = OpenAI()
    stream = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        instructions=build_instructions(),
        input=build_input(question, history),
        **choose_generation_settings(task_type="factual_learning"),
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
    print("Smart Q&A challenge. Use /reset to clear context or /quit to exit.")

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
