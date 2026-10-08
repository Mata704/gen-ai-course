"""Complete Session 7 baseline: a robust loop with an observable trace."""

from __future__ import annotations

import sys
from pathlib import Path


SESSION_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SESSION_DIR))

from agent_service import AgentService  # noqa: E402


def main() -> None:
    service = AgentService()
    session_id = "demo-user"
    questions = [
        "Why was Apollo 13 described as a successful failure?",
        "When did that mission launch and splash down?",
    ]

    for question in questions:
        reply = service.chat(session_id, question)
        print(f"\nUser: {question}")
        print(f"Trace: {reply.trace or ['direct answer']}")
        print(f"Assistant: {reply.answer}")

    print(f"\nSession reset: {service.reset(session_id)}")


if __name__ == "__main__":
    main()
