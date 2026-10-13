"""Exercise 4: inspect the same session before and after restarting only the API."""

import argparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["before", "after"])
    parser.add_argument("--session-id", required=True, help="Copy the ID shown in the UI sidebar")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=90.0) as client:
        response = client.get(f"/session-state/{args.session_id}")
        response.raise_for_status()
        state = response.json()
        print(f"\nSession: {args.session_id}")
        print("| API runtime | Service | Session exists | History messages |")
        print("| --- | --- | --- | --- |")
        print(f"| {state['runtime_id']} | {state['service_id']} | {state['session_exists']} | {state['history_messages']} |")
        if args.phase == "before":
            if not state["history_messages"]:
                raise RuntimeError("First ask about Apollo 13 in the UI and copy that session ID.")
            print("Keep the browser open. Restart ONLY the API, then run the after phase.")
            return
        if state["history_messages"]:
            raise RuntimeError("History is still present. Restart only the API and retry before sending another question.")
        print("The API has no history for this ID. Compare with the messages still visible in the UI.")
        print("In the UI, try 'When did that mission launch and splash down?'.")
        print("Then try 'When did Apollo 13 launch and splash down?'.")
        print("Compare answers and the history count shown with each response.")
        print("A model can guess the mission; a plausible answer does NOT prove history survived.")


if __name__ == "__main__":
    main()
