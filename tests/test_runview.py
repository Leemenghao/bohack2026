"""Tests for rebuilding a recorded run. Filesystem only."""

import json
import shutil
import unittest
import uuid
from pathlib import Path

from runview import build_events, list_recorded_runs, load_run_view

RUNS_ROOT = Path(__file__).resolve().parent / ".runs"


class RecordedRunTest(unittest.TestCase):
    def setUp(self):
        self.root = RUNS_ROOT / uuid.uuid4().hex[:8]
        self.run = self.root / "abcdef123456"
        self.run.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name, payload):
        path = self.run / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_empty_root_lists_nothing(self):
        self.assertEqual(list_recorded_runs(self.root / "missing"), [])

    def test_run_without_report_is_skipped(self):
        self.write("summary.json", {"question": "没有报告"})
        self.assertEqual(list_recorded_runs(self.root), [])

    def test_listing_reports_question_and_elapsed(self):
        (self.run / "report.md").write_text("# 报告", encoding="utf-8")
        self.write("summary.json", {"question": "前缀缓存", "elapsed_seconds": 21.99, "memory_from": "prev0001"})
        rows = list_recorded_runs(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "abcdef123456")
        self.assertEqual(rows[0]["question"], "前缀缓存")
        self.assertEqual(rows[0]["elapsed_seconds"], 21.99)
        self.assertEqual(rows[0]["memory_from"], "prev0001")

    def test_events_are_rebuilt_in_order(self):
        self.write("summary.json", {"budget": {"limit_calls": 8}, "memory_from": "prev0001"})
        self.write("search-aaaaaaaa.json", {"query": "mlx cache", "sources": [
            {"source_id": "mlx-cache", "title": "MLX", "url": "https://example.com", "excerpt": "…"},
        ]})
        self.write("source-bbbbbbbb.json", {"source_id": "mlx-cache", "title": "MLX", "content_kind": "paper_abstract"})
        self.write("experiment-cccccccc.json", {"workload": "shared", "reason": "基线", "cache_first": False,
                                               "summary": {"median_ttft_ms_off": 1, "median_ttft_ms_on": 0.5}})

        events = build_events(self.run)
        kinds = [event["type"] for event in events]
        self.assertEqual(kinds[:3], ["budget", "memory", "source"])
        self.assertIn("source_fetched", kinds)
        self.assertEqual(kinds.count("started"), 1)
        self.assertEqual(kinds.count("completed"), 1)

    def test_view_contains_report_and_usage(self):
        (self.run / "report.md").write_text("结论：降幅 84.6%", encoding="utf-8")
        self.write("summary.json", {
            "question": "前缀缓存", "model": "deepseek-flash", "elapsed_seconds": 22.0,
            "usage": {"input_tokens": 8967, "output_tokens": 1759},
        })
        view = load_run_view(self.run)
        self.assertEqual(view["status"], "complete")
        self.assertIn("84.6%", view["result"]["report"])
        self.assertEqual(view["result"]["usage"]["input_tokens"], 8967)

    def test_missing_report_returns_none(self):
        self.assertIsNone(load_run_view(self.run))

    def test_broken_summary_does_not_crash(self):
        (self.run / "report.md").write_text("# 报告", encoding="utf-8")
        (self.run / "summary.json").write_text("{ not json", encoding="utf-8")
        view = load_run_view(self.run)
        self.assertEqual(view["status"], "complete")
        self.assertEqual(view["result"]["question"], "")


if __name__ == "__main__":
    unittest.main()
