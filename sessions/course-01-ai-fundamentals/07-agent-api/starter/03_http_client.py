"""Session 7 exercise 3: consume the Copilot API through a robust HTTP client."""
"""Solution for Session 7 exercise 3."""

from __future__ import annotations

import argparse
import uuid
from typing import Any

import httpx


class CopilotApiError(RuntimeError):
    pass


class CopilotApiClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.client.request(method, path, json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise CopilotApiError(f"The API timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise CopilotApiError(f"Could not reach the API: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", exc.response.text)
            except ValueError:
                detail = exc.response.text
            raise CopilotApiError(
                f"API returned {exc.response.status_code}: {detail}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise CopilotApiError("The API returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise CopilotApiError("The API returned JSON that is not an object.")
        return data

    def health(self) -> bool:
        return self._request("GET", "/health").get("status") == "ok"

    def chat(self, session_id: str, question: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/chat",
            {"session_id": session_id, "question": question},
        )
        if not isinstance(response.get("answer"), str):
            raise CopilotApiError("The API response has no string answer.")
        return response

    def reset(self, session_id: str) -> bool:
        response = self._request(
            "POST", "/sessions/reset", {"session_id": session_id}
        )
        if not isinstance(response.get("cleared"), bool):
            raise CopilotApiError("The API response has no boolean cleared field.")
        return response["cleared"]


def run_demo(client: CopilotApiClient) -> None:
    if not client.health():
        raise CopilotApiError("The API health check did not return status=ok.")

    session_id = str(uuid.uuid4())
    questions = [
        "Why was Apollo 13 described as a successful failure?",
        "When did that mission launch and splash down?",
    ]
    try:
        for question in questions:
            response = client.chat(session_id, question)
            print(f"\nUser: {question}")
            print(f"Trace: {response.get('trace') or ['direct answer']}")
            print(f"Assistant: {response['answer']}")
    finally:
        print(f"\nSession reset: {client.reset(session_id)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    client = CopilotApiClient(args.base_url)
    try:
        run_demo(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()
