"""Report session state."""

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
                raise RuntimeError("No history messages found for the supplied session_id in phase 'before'.")
            return
        if state["history_messages"]:
            raise RuntimeError(f"Unexpected history_messages in phase 'after': {state['history_messages']}.")


if __name__ == "__main__":
    main()
