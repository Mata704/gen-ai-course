"""Run requests in two service modes."""

import argparse
import time
import uuid

from app.observed_service import ObservedAgentService


QUESTIONS = [
    "Why was Apollo 13 described as a successful failure?",
    "What was Apollo 11's main achievement?",
]


def compare(mode: str) -> None:
    service = None
    preparations = 0
    rows = []
    print(f"\n=== {mode.upper()} ===", flush=True)
    for number, question in enumerate(QUESTIONS, 1):
        started = time.perf_counter()
        prepared_now = service is None or mode == "repeated"
        if prepared_now:
            service = ObservedAgentService()
            preparations += 1
        print(f"\nQuestion {number}: {question}", flush=True)
        reply = service.chat(str(uuid.uuid4()), question)
        seconds = time.perf_counter() - started
        print(f"Answer: {reply.answer}\nTools: {reply.tools_used}\nTrace: {reply.trace}")
        rows.append((number, service.service_id, prepared_now, seconds))
        service.sessions.clear()

    print("\n| Request | Service | Prepared now | Total seconds |")
    print("| --- | --- | --- | --- |")
    for number, service_id, prepared_now, seconds in rows:
        print(f"| {number} | {service_id} | {prepared_now} | {seconds:.2f} |")
    print(f"Document embedding batches: {preparations}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["repeated", "reused", "both"], default="both")
    args = parser.parse_args()
    print("Real embedding and LLM requests. The default comparison sends four questions in total.")
    for mode in (["repeated", "reused"] if args.mode == "both" else [args.mode]):
        compare(mode)


if __name__ == "__main__":
    main()
