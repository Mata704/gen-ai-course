"""Compare semantic, lexical and hybrid retrieval on the same questions."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


SESSIONS_DIR = Path(__file__).resolve().parents[2]
SESSION_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SESSIONS_DIR))

from rag_course_support import require_api_key  # noqa: E402
from session_05_support import (  # noqa: E402
    render_retrieval_report,
    run_retrieval_comparison,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("development", "holdout"), default="development")
    parser.add_argument("--top-k", type=int, default=2)
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")

    load_dotenv()
    require_api_key()
    comparisons = run_retrieval_comparison(OpenAI(), args.split, args.top_k)
    report = render_retrieval_report(comparisons, args.split, args.top_k)

    output = SESSION_DIR / "reports" / f"hybrid-retrieval-{args.split}.md"
    output.parent.mkdir(exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved report: {output}")


if __name__ == "__main__":
    main()
