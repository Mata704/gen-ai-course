"""Session 1 reference: a streaming Smart Q&A with basic run metrics."""

import os
import time

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

PRICE_PER_MILLION_TOKENS = {
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
}


def build_instructions() -> str:
    """Define an explicit contract for a learning assistant."""
    return """You are a concise and rigorous learning assistant.

Answer in clear Portuguese. Explain concepts, but do not invent dates, links,
policies, assessments, or course-specific decisions that are not in the
provided context. When essential information is missing, say what you do not
know and suggest a useful next step or ask one focused question.
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


def choose_generation_settings(task_type: str) -> dict[str, int | float]:
    """Use greater consistency for facts and more variety for ideation."""
    settings_by_task = {
        "factual_learning": {"temperature": 0.2, "max_output_tokens": 400},
        "creative_brainstorming": {"temperature": 0.8, "max_output_tokens": 500},
    }
    return settings_by_task[task_type]


def display_metrics(
    *,
    model: str,
    usage: object | None,
    started_at: float,
    first_token_at: float | None,
    finished_at: float,
) -> None:
    """Display token usage, latency, and an approximate request cost."""
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)

    print("---")
    print(f"Model: {model}")
    print(f"Total latency: {finished_at - started_at:.2f}s")
    if first_token_at is not None:
        print(f"Time to first token: {first_token_at - started_at:.2f}s")

    if None not in (input_tokens, output_tokens, total_tokens):
        print(f"Input tokens: {input_tokens}")
        print(f"Output tokens: {output_tokens}")
        print(f"Total tokens: {total_tokens}")

        prices = PRICE_PER_MILLION_TOKENS.get(model)
        if prices is not None:
            estimated_cost = (
                input_tokens * prices["input"] + output_tokens * prices["output"]
            ) / 1_000_000
            print(f"Estimated cost, excluding cache: ${estimated_cost:.6f}")
        else:
            print("Estimated cost: no price table for this model.")
    else:
        print("Token usage and estimated cost: usage was not returned by the API.")


def stream_answer(question: str, history: list[dict[str, str]]) -> str:
    """Run the final version: streaming, context, settings, and metrics."""
    client = OpenAI()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    started_at = time.perf_counter()
    stream = client.responses.create(
        model=model,
        instructions=build_instructions(),
        input=build_input(question, history),
        **choose_generation_settings("factual_learning"),
        stream=True,
    )

    answer_parts: list[str] = []
    first_token_at: float | None = None
    usage: object | None = None
    for event in stream:
        if event.type == "response.output_text.delta":
            if first_token_at is None:
                first_token_at = time.perf_counter()
            answer_parts.append(event.delta)
            print(event.delta, end="", flush=True)
        elif event.type == "response.completed":
            usage = event.response.usage

    finished_at = time.perf_counter()
    print("\n")
    display_metrics(
        model=model,
        usage=usage,
        started_at=started_at,
        first_token_at=first_token_at,
        finished_at=finished_at,
    )
    return "".join(answer_parts)


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")

    history: list[dict[str, str]] = []
    print("Smart Q&A. Use /reset to clear context or /quit to exit.")

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
