"""Compare two frozen RAG runs and decide whether to release the candidate."""

import argparse
import json
import sys
from pathlib import Path


SESSIONS_DIR = Path(__file__).resolve().parents[2]
SESSION_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SESSIONS_DIR))

from session_05_support import (  # noqa: E402
    compare_rag_versions,
    load_json,
    render_version_report,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=SESSION_DIR / "test-data" / "rag-version-runs.json",
    )
    args = parser.parse_args()

    cases = load_json(args.fixture)
    results = compare_rag_versions(cases)
    report = render_version_report(results, cases)

    output_dir = SESSION_DIR / "reports"
    output_dir.mkdir(exist_ok=True)
    markdown_path = output_dir / "rag-comparison.md"
    json_path = output_dir / "rag-comparison.json"
    markdown_path.write_text(report, encoding="utf-8")
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(report)
    print(f"Saved report: {markdown_path}")


if __name__ == "__main__":
    main()
