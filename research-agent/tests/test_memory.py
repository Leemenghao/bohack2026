"""Tests for cross-run memory. Filesystem only, no model."""

import os
import shutil
import time
import unittest
import uuid
from pathlib import Path

from research_agent.memory import MAX_MEMORY_CHARS, condense, list_runs, load_previous, memory_block

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

    def test_only_shared_summaries_are_carried_into_cli(self):
        from research_agent.conversation_store import ConversationStore
        store = ConversationStore(self.root)
        store.save_summary("000000000001", "000000000001", "共享摘要", "2026-11-14", "test")
        store.save_summary("000000000002", "000000000002", "私有摘要", "2026-11-15", "test")
        self.assertIsNone(load_previous(self.root))
        store.update_session("000000000001", shared=True)
        self.assertEqual(load_previous(self.root)["text"], "共享摘要")
        self.assertIsNone(load_previous(self.root, exclude=self.root / "000000000001"))
        store.update_session("000000000001", archived=True)
        self.assertIsNone(load_previous(self.root))

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
