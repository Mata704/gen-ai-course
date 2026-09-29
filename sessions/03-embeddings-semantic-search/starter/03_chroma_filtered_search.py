"""Session 3 challenge: search a Chroma collection with metadata filters."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.50"))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SESSION_DIR = Path(__file__).resolve().parent.parent
DOCUMENTS_DIR = (
    PROJECT_ROOT
    / "projects"
    / "course-01-generative-ai"
    / "knowledge-copilot"
    / "data"
    / "documents"
)
METADATA_PATH = SESSION_DIR / "test-data" / "apollo-metadata.json"
CHROMA_PATH = PROJECT_ROOT / ".chroma" / "session-03"
COLLECTION_NAME = "apollo_missions"


def load_records() -> list[dict[str, Any]]:
    """Pair each supplied document with its prepared metadata."""
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    metadata_by_source = {item["source"]: item for item in metadata}
    return [
        {
            "source": path.name,
            "text": path.read_text(encoding="utf-8"),
            "metadata": {
                key: value
                for key, value in metadata_by_source[path.name].items()
                if key != "source"
            },
        }
        for path in sorted(DOCUMENTS_DIR.glob("*.md"))
    ]


def create_embeddings(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def build_where_filter(
    mission_type: str | None, min_year: int | None
) -> dict[str, Any] | None:
    """Build a Chroma filter from the optional mission type and year."""
    conditions: list[dict[str, Any]] = []
    if mission_type is not None:
        conditions.append({"mission_type": {"$eq": mission_type}})
    if min_year is not None:
        conditions.append({"year": {"$gte": min_year}})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}

def index_documents(
    collection: Collection,
    records: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    """Upsert passages with stable IDs so repeated runs do not add duplicates."""

    if len(records) != len(embeddings):
        raise ValueError(
            f"Expected {len(records)} embeddings, got {len(embeddings)}."
        )

    collection.upsert(
        documents=[record["text"] for record in records],
        metadatas=[record["metadata"] for record in records],
        ids=[record["source"] for record in records],
        embeddings=embeddings,
    )


def search_collection(
    collection: Collection,
    query_embedding: list[float],
    where: dict[str, Any] | None,
    top_k: int,
    min_similarity: float,
) -> list[dict[str, Any]]:
    """Query Chroma and return source, text, metadata, and similarity."""

    if top_k < 1:
        raise ValueError("top_k must be at least 1.")
    response = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    results = []
    for source, text, metadata, distance in zip(
        response["ids"][0],
        response["documents"][0],
        response["metadatas"][0],
        response["distances"][0],
        strict=True,
    ):
        similarity = 1.0 - float(distance)
        if similarity >= min_similarity:
            results.append(
                {
                    "source": source,
                    "text": text,
                    "metadata": metadata,
                    "similarity": similarity,
                }
            )
    return results



def get_collection() -> Collection:
    """Open the persistent collection, configured to use cosine distance."""
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        configuration={"hnsw": {"space": "cosine"}},
        embedding_function=None,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="Question to search for.")
    parser.add_argument("--mission-type")
    parser.add_argument("--min-year", type=int)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-similarity", type=float, default=MIN_SIMILARITY)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY in your local .env file first.")

    records = load_records()
    client = OpenAI()
    embeddings = create_embeddings(client, [record["text"] for record in records])
    collection = get_collection()
    index_documents(collection, records, embeddings)

    question = (
        args.query or input("Ask a question about the Apollo missions: ")
    ).strip()
    if not question:
        raise ValueError("Please enter a question.")
    query_embedding = create_embeddings(client, [question])[0]
    where = build_where_filter(args.mission_type, args.min_year)
    results = search_collection(
        collection,
        query_embedding,
        where=where,
        top_k=args.top_k,
        min_similarity=args.min_similarity,
    )

    if not results:
        print("No result met the evidence threshold and filters.")
        return
    for result in results:
        print(
            f"{result['similarity']:.3f}  {result['source']}  "
            f"year={result['metadata']['year']}  "
            f"type={result['metadata']['mission_type']}"
        )
        print(f"{result['text'].strip()}\n")


if __name__ == "__main__":
    main()
