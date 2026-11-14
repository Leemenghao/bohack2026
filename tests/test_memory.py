"""Tests for cross-run memory. Filesystem only, no model."""

import os
import shutil
import time
import unittest
import uuid
from pathlib import Path

from memory import MAX_MEMORY_CHARS, condense, list_runs, load_previous, memory_block

# Fixtures live inside the workspace: some sandboxes deny deleting the system temp
# directory, which would otherwise turn a passing test into a teardown error.
RUNS_ROOT = Path(__file__).resolve().parent / ".runs"


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.root = RUNS_ROOT / uuid.uuid4().hex[:8]
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make_run(self, name, text, age=0):
        run = self.root / name
        run.mkdir()
        report = run / "report.md"
        report.write_text(text, encoding="utf-8")
        # Deterministic ordering regardless of filesystem timestamp resolution.
        stamp = time.time() - age
        os.utime(report, (stamp, stamp))
        return run

    def test_empty_root_has_no_memory(self):
        self.assertEqual(list_runs(self.root), [])
        self.assertIsNone(load_previous(self.root))
        self.assertEqual(memory_block(None), "")

    def test_newest_finished_run_wins(self):
        self.make_run("old", "旧结论", age=100)
        self.make_run("new", "新结论", age=1)
        previous = load_previous(self.root)
        self.assertEqual(previous["run_id"], "new")

    def test_current_run_is_excluded(self):
        self.make_run("older", "更早的结论", age=50)
        current = self.make_run("current", "本轮报告", age=0)
        previous = load_previous(self.root, exclude=current)
        self.assertEqual(previous["run_id"], "older")

    def test_run_without_report_is_ignored(self):
        (self.root / "unfinished").mkdir()
        self.assertEqual(list_runs(self.root), [])

    def test_condense_keeps_head_and_marks_truncation(self):
        long_text = "结论开头。" * 300
        result = condense(long_text, limit=MAX_MEMORY_CHARS)
        self.assertLessEqual(len(result), MAX_MEMORY_CHARS + 20)
        self.assertTrue(result.endswith("（已截断）"))
        self.assertTrue(result.startswith("结论开头。"))

    def test_condense_leaves_short_reports_untouched(self):
        self.assertEqual(condense("短结论"), "短结论")

    def test_memory_block_states_scope(self):
        block = memory_block({"run_id": "abc123", "text": "上一轮：降幅 84.6%"})
        self.assertIn("abc123", block)
        self.assertIn("84.6%", block)
        self.assertIn("不能当作本轮实测结果", block)


if __name__ == "__main__":
    unittest.main()
