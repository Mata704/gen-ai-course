"""Session 3 baseline: create embeddings for the prepared project passages."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
DOCUMENTS_DIR = (
    Path(__file__).resolve().parents[3]
    / "projects"
    / "course-01-generative-ai"
    / "knowledge-copilot"
    / "data"
    / "documents"
)
SESSION_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = SESSION_DIR / "generated" / "passage-embeddings.json"


@dataclass(frozen=True)
class Passage:
    """One prepared retrieval unit from the mini-project corpus."""

    source: str
    text: str


def load_passages() -> list[Passage]:
    """Load each supplied Markdown file as one retrieval passage."""
    return [
        Passage(source=path.name, text=path.read_text(encoding="utf-8"))
        for path in sorted(DOCUMENTS_DIR.glob("*.md"))
    ]


def create_embeddings(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Embed multiple passages in one API request."""
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def main() -> None:
    passages = load_passages()
    client = OpenAI()
    embeddings = create_embeddings(client, [passage.text for passage in passages])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "model": EMBEDDING_MODEL,
                "dimensions": len(embeddings[0]) if embeddings else 0,
                "passages": [
                    {"source": passage.source, "embedding": embedding}
                    for passage, embedding in zip(passages, embeddings, strict=True)
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Model: {EMBEDDING_MODEL}")
    print(f"Passages embedded: {len(passages)}\n")

    for passage, embedding in zip(passages, embeddings, strict=True):
        print(f"{passage.source}: {len(embedding)} dimensions")
    print(f"\nEmbeddings saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
