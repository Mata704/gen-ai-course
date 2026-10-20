"""Session 6 exercise 2: complete one strict tool-calling lifecycle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


SESSIONS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SESSIONS_DIR))

from rag_course_support import GENERATION_MODEL, require_api_key  # noqa: E402


load_dotenv()

DATA_FILE = Path(__file__).resolve().parents[1] / "test-data" / "mission-timelines.json"
Timeline = dict[str, str | None]


def load_timelines(path: Path = DATA_FILE) -> dict[str, Timeline]:
    timelines = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(timelines, dict) or not timelines:
        raise ValueError(f"No mission timelines found in {path}")
    return timelines


def build_tool_definition() -> dict[str, Any]:
    """Define get_mission_timeline with a strict JSON schema."""
    return {
        "type": "function",
        "name": "get_mission_timeline",
        "description": "Get the exact launch, lunar landing, and splashdown dates.",
        "parameters": {
            "type": "object",
            "properties": {
                "mission": {
                    "type": "string",
                    "description": "Apollo mission name, for example Apollo 11.",
                }
            },
            "required": ["mission"],
            "additionalProperties": False,
        },
        "strict": True,
    }


def execute_tool_call(call: Any, timelines: dict[str, Timeline]) -> str:
    """Execute a validated call and always return a JSON string."""
    if call.name != "get_mission_timeline":
        return json.dumps({"ok": False, "error": f"Unknown tool: {call.name}"})

    try:
        arguments = json.loads(call.arguments)
    except (TypeError, json.JSONDecodeError):
        return json.dumps({"ok": False, "error": "Arguments are not valid JSON."})

    if not isinstance(arguments, dict) or not isinstance(arguments.get("mission"), str):
        return json.dumps({"ok": False, "error": "mission must be a string."})

    requested = arguments["mission"].strip().casefold()
    mission = next((name for name in timelines if name.casefold() == requested), None)
    if mission is None:
        return json.dumps(
            {"ok": False, "error": f"Mission not found: {arguments['mission']}"}
        )
    return json.dumps(
        {"ok": True, "mission": mission, "timeline": timelines[mission]}
    )


def answer_with_tool(
    client: OpenAI,
    question: str,
    timelines: dict[str, Timeline],
) -> tuple[str, list[str]]:
    """Let the model call the local tool, then produce the final answer."""
    if not question.strip():
        raise ValueError("question cannot be empty.")

    tool = build_tool_definition()
    model_input: list[Any] = [{"role": "user", "content": question.strip()}]

    first_response = client.responses.create(
        model=GENERATION_MODEL,
        instructions=(
            "You answer Apollo questions concisely. Use get_mission_timeline for "
            "exact launch, landing, or splashdown dates."
        ),
        input=model_input,
        tools=[tool],
        parallel_tool_calls=False,
        store=False,
    )

    model_input.extend(first_response.output)

    calls = [item for item in first_response.output if item.type == "function_call"]
    if not calls:
        return first_response.output_text.strip(), []

    for call in calls:
        model_input.append(
            {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": execute_tool_call(call, timelines),
            }
        )

    final_response = client.responses.create(
        model=GENERATION_MODEL,
        instructions="Answer concisely from the tool result. Explain tool errors plainly.",
        input=model_input,
        tools=[tool],
        tool_choice="none",
        parallel_tool_calls=False,
        store=False,
    )
    return final_response.output_text.strip(), [call.name for call in calls]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default="When did Apollo 11 land?")
    args = parser.parse_args()

    require_api_key()
    answer, trace = answer_with_tool(OpenAI(), args.question, load_timelines())
    print(f"Tools used: {trace or ['none']}")
    print(f"Assistant: {answer}")


if __name__ == "__main__":
    main()
