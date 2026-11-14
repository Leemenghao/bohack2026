"""Smoke tests for the local source collection.

Run from the project root:

    python -m unittest discover -s tests -v

No network, no Apple Silicon, no third-party packages: `sources.py` is loaded
straight from the vendored tree so the tests work in a fresh clone.

The module is loaded by path instead of imported as `deepagents.research.sources`
because the parent package `deepagents/__init__.py` pulls in langchain, which we
do not want to require just to test keyword ranking.
"""

import importlib.util
import unittest
from pathlib import Path

SOURCE_FILE = Path(__file__).resolve().parents[1] / "vendor" / "deepagents" / "deepagents" / "research" / "sources.py"
spec = importlib.util.spec_from_file_location("research_sources", SOURCE_FILE)
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)

SOURCES = sources.SOURCES
find_sources = sources.find_sources


class FindSourcesTest(unittest.TestCase):
    def setUp(self):
        self.ids = {entry[0] for entry in SOURCES}

    def test_collection_has_expected_sources(self):
        self.assertIn("mlx-cache", self.ids)
        self.assertIn("vllm-apc", self.ids)

    def test_prefix_cache_query_hits_mlx_source(self):
        hits = find_sources("MLX prefix cache 前缀复用")
        self.assertTrue(hits)
        self.assertIn("mlx-cache", [hit["source_id"] for hit in hits])

    def test_vllm_query_hits_vllm_source(self):
        hits = find_sources("vllm prefill 预填充")
        self.assertIn("vllm-apc", [hit["source_id"] for hit in hits])

    def test_results_are_capped_at_three(self):
        hits = find_sources("mlx prefix cache 前缀 复用 命中 vllm prefill 延迟")
        self.assertLessEqual(len(hits), 3)

    def test_matching_is_case_insensitive(self):
        lower = find_sources("mlx cache")
        upper = find_sources("MLX CACHE")
        self.assertEqual([hit["source_id"] for hit in lower], [hit["source_id"] for hit in upper])

    def test_ascii_keywords_match_whole_words_only(self):
        # "xmlx" contains "mlx" but must not match on a substring.
        self.assertEqual(find_sources("xmlx"), [])

    def test_unrelated_query_returns_nothing(self):
        self.assertEqual(find_sources("今天天气怎么样"), [])

    def test_every_source_is_addressable(self):
        for source_id, title, url, excerpt, keywords in SOURCES:
            self.assertTrue(source_id)
            self.assertTrue(title)
            self.assertTrue(url.startswith("https://"), f"{source_id} url should be https")
            self.assertTrue(excerpt)
            self.assertTrue(keywords, f"{source_id} needs keywords for ranking")


if __name__ == "__main__":
    unittest.main()
