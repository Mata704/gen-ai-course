"""Session 2 example: transform a support request into a typed result."""

import os
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel


class CourseRequest(BaseModel):
    """A deliberately small first schema for a course-support request."""

    intent: Literal["technical_issue", "course_question", "feedback", "other"]
    summary: str
    needs_follow_up: bool


load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")

def main() -> None:
    message = input("Write a support request: ").strip()
    if not message:
        raise ValueError("Please enter a support request.")

    client = OpenAI()
    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        instructions=(
            "Classify the course-support request. Use 'other' whenever it does "
            "not fit the listed intents."
        ),
        input=message,
        text_format=CourseRequest,
    )

    result = response.output_parsed
    if result is None:
        print("No usable structured result was returned.")
    else:
        print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
