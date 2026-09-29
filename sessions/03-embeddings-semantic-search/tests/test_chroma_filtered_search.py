"""Deterministic tests for the Session 3 Chroma exercise."""

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any


EXERCISE_PATH = (
    Path(__file__).parent.parent / "starter" / "03_chroma_filtered_search.py"
)


def load_exercise() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chroma_exercise", EXERCISE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load exercise at {EXERCISE_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXERCISE = load_exercise()


class FakeCollection:
    def __init__(self) -> None:
        self.upsert_args: dict[str, Any] | None = None
        self.query_args: dict[str, Any] | None = None

    def upsert(self, **kwargs: Any) -> None:
        self.upsert_args = kwargs

    def query(self, **kwargs: Any) -> dict[str, list[list[Any]]]:
        self.query_args = kwargs
        return {
            "ids": [["apollo-15.md", "apollo-13.md"]],
            "documents": [["Lunar rover mission", "Aborted landing"]],
            "metadatas": [[{"year": 1971}, {"year": 1970}]],
            "distances": [[0.1, 0.4]],
        }


class ChromaFilteredSearchTests(unittest.TestCase):
    def test_builds_none_single_and_combined_filters(self):
        filters = EXERCISE.SearchFilters

        self.assertIsNone(EXERCISE.build_where_filter(filters()))
        self.assertEqual(
            EXERCISE.build_where_filter(filters(mission_type="lunar_landing")),
            {"mission_type": {"$eq": "lunar_landing"}},
        )
        self.assertEqual(
            EXERCISE.build_where_filter(filters(min_year=1970)),
            {"year": {"$gte": 1970}},
        )
        self.assertEqual(
            EXERCISE.build_where_filter(
                filters(mission_type="lunar_landing", min_year=1970)
            ),
            {
                "$and": [
                    {"mission_type": {"$eq": "lunar_landing"}},
                    {"year": {"$gte": 1970}},
                ]
            },
        )

    def test_index_upserts_stable_ids_and_rejects_mismatched_embeddings(self):
        collection = FakeCollection()
        record = EXERCISE.DocumentRecord(
            source="apollo-15.md",
            text="Lunar rover mission",
            metadata={"year": 1971, "landed_on_moon": True},
        )

        with self.assertRaises(ValueError):
            EXERCISE.index_documents(collection, [record], [])
        self.assertIsNone(collection.upsert_args)

        EXERCISE.index_documents(collection, [record], [[0.1, 0.2]])

        self.assertEqual(collection.upsert_args["ids"], ["apollo-15.md"])
        self.assertEqual(collection.upsert_args["documents"], [record.text])
        self.assertEqual(collection.upsert_args["metadatas"], [record.metadata])
        self.assertEqual(collection.upsert_args["embeddings"], [[0.1, 0.2]])

    def test_search_normalizes_results_and_applies_similarity_threshold(self):
        collection = FakeCollection()

        results = EXERCISE.search_collection(
            collection,
            [0.2, 0.8],
            EXERCISE.SearchFilters(mission_type="lunar_landing", min_year=1970),
            top_k=2,
            min_similarity=0.8,
        )

        self.assertEqual(collection.query_args["n_results"], 2)
        self.assertEqual(
            collection.query_args["where"],
            {
                "$and": [
                    {"mission_type": {"$eq": "lunar_landing"}},
                    {"year": {"$gte": 1970}},
                ]
            },
        )
        self.assertEqual(
            collection.query_args["include"],
            ["documents", "metadatas", "distances"],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "apollo-15.md")
        self.assertEqual(results[0].text, "Lunar rover mission")
        self.assertEqual(results[0].metadata, {"year": 1971})
        self.assertAlmostEqual(results[0].similarity, 0.9)

    def test_search_rejects_top_k_below_one(self):
        with self.assertRaises(ValueError):
            EXERCISE.search_collection(
                FakeCollection(), [], EXERCISE.SearchFilters(), 0, 0.5
            )


if __name__ == "__main__":
    unittest.main()