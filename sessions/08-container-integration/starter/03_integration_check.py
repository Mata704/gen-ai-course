"""Exercise 3: inspect API behaviour and UI reachability, not browser interaction."""

import argparse
import uuid

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ui-url", default="http://127.0.0.1:8501")
    args = parser.parse_args()
    session_id = str(uuid.uuid4())
    with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=90.0) as client:
        for label, url in [("API health", "/health"), ("UI page", args.ui_url)]:
            response = client.get(url)
            response.raise_for_status()
            print(f"{label}: reachable")
        try:
            for question in [
                "Why was Apollo 13 described as a successful failure?",
                "When did that mission launch and splash down?",
            ]:
                response = client.post("/chat", json={"session_id": session_id, "question": question})
                response.raise_for_status()
                data = response.json()
                if not isinstance(data.get("answer"), str) or not data["answer"].strip():
                    raise RuntimeError("Missing non-empty answer")
                if not isinstance(data.get("trace"), list) or not isinstance(data.get("tools_used"), list):
                    raise RuntimeError("Missing trace or tools_used list")
                print(f"\nQuestion: {question}\nAnswer: {data['answer']}")
                print(f"Tools: {data['tools_used']}\nTrace: {data['trace']}")
                print(f"History before question: {data['history_messages_before']}")
        finally:
            try:
                response = client.post("/sessions/reset", json={"session_id": session_id})
                response.raise_for_status()
                print(f"\nSession reset: {response.json()['cleared']}")
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                print(f"\nCleanup failed separately: {exc}")
    print("\nDirect API checks passed; UI page is reachable.")
    print("NOT TESTED: submitting a question through the UI, or factual correctness.")
    print("Now send a question in the browser and compare the result.")


if __name__ == "__main__":
    main()
