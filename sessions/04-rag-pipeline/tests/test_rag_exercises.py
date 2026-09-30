"""API-free tests for the deterministic parts of Session 4."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SESSION_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SESSION_DIR))


def load_exercise(name: str, filename: str):
    path = SESSION_DIR / "04-rag-pipeline" / "starter" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load exercise at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHUNKING = load_exercise("session4_chunking", "02_chunking_lab.py")
GROUNDED = load_exercise("session4_grounded", "03_grounded_rag.py")
SUPPORT = sys.modules["rag_course_support"]


class ChunkingTests(unittest.TestCase):
    def setUp(self):
        self.document = SUPPORT.Document(
            source="apollo.md",
            title="Apollo missions",
            text=(
                "# Apollo missions\n\n## Apollo 11\n\n"
                "one two three four five six seven eight nine ten\n\n"
                "## Apollo 12\n\nSurveyor three visited the Moon."
            ),
        )

    def test_fixed_chunks_keep_overlap_and_stable_identity(self):
        chunks = CHUNKING.fixed_size_chunks([self.document], 4, 1)

        self.assertEqual(chunks[0].text, "# Apollo missions ##")
        self.assertEqual(chunks[0].chunk_id, "apollo.md::fixed:0001")
        self.assertEqual(chunks[1].text.split()[0], chunks[0].text.split()[-1])
        self.assertEqual(chunks[-1].text.split()[-1], "Moon.")

    def test_chunking_rejects_invalid_sizes_and_overlap(self):
        with self.assertRaises(ValueError):
            CHUNKING.fixed_size_chunks([self.document], 0, 0)
        with self.assertRaises(ValueError):
            CHUNKING.structure_aware_chunks([self.document], 4, 4)

    def test_structure_chunks_retain_heading_context(self):
        chunks = CHUNKING.structure_aware_chunks([self.document], 3, 1)

        self.assertTrue(chunks[0].text.startswith("Apollo missions > Apollo 11\n\n"))
        self.assertTrue(any("Apollo missions > Apollo 12" in chunk.text for chunk in chunks))
        self.assertEqual(len(chunks), len({chunk.chunk_id for chunk in chunks}))


class GroundedRagTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [
            SUPPORT.Chunk(f"id-{index}", f"source-{index}.md", "Title", f"evidence {index}")
            for index in range(4)
        ]
        self.results = [
            SUPPORT.SearchResult(chunk, score)
            for chunk, score in zip(self.chunks, [0.9, 0.8, 0.1, 0.7], strict=True)
        ]

    def test_context_selection_respects_score_budget_and_order(self):
        with patch.object(GROUNDED, "count_tokens", side_effect=lambda text: text.count("[SOURCE:") * 5):
            selected = GROUNDED.select_context(self.results, max_tokens=10, min_score=0.2)

        self.assertEqual([item.chunk.chunk_id for item in selected], ["id-0", "id-1"])

    def test_context_selection_rejects_invalid_budget(self):
        with self.assertRaises(ValueError):
            GROUNDED.select_context(self.results, max_tokens=0, min_score=0.0)

    def test_citation_requires_known_chunk_and_verbatim_quote(self):
        selected = self.results[:1]
        valid = GROUNDED.GroundedAnswer(
            answer="Evidence supports this.",
            answerable=True,
            citations=[GROUNDED.Citation("source-0.md", "id-0", "evidence   0")],
        )
        invalid = GROUNDED.GroundedAnswer(
            answer="Unsupported.",
            answerable=True,
            citations=[GROUNDED.Citation("other.md", "missing", "not present")],
        )

        self.assertEqual(GROUNDED.validate_citations(valid, selected), [])
        errors = GROUNDED.validate_citations(invalid, selected)
        self.assertTrue(any("Unknown source/chunk pair" in error for error in errors))

    def test_abstention_must_not_cite(self):
        answer = GROUNDED.GroundedAnswer(
            answer="Not enough information.",
            answerable=False,
            citations=[GROUNDED.Citation("source-0.md", "id-0", "evidence 0")],
        )

        self.assertTrue(any("Abstentions" in error for error in GROUNDED.validate_citations(answer, self.results[:1])))


if __name__ == "__main__":
    unittest.main()
