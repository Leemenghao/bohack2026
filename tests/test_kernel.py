import tempfile
import unittest
from pathlib import Path

from benchmark.row_normalization import BASELINE, run_benchmark, validate_code
from research_agent.research.kernel import session_workspace
from runview import save_run


class KernelTest(unittest.TestCase):
    def test_correctness_and_bad_candidate(self):
        code = "def normalize(x):\n    return x / np.maximum(np.sqrt(np.sum(x*x, axis=1, keepdims=True)), 1e-12)\n"
        for suite in ("development", "validation"):
            result = run_benchmark(code, suite)["summary"]
            self.assertTrue(result["correct"])
            self.assertEqual(len(result["cases"]), 3)
            self.assertTrue(all(len(c["samples_ms"]["candidate"]) == 9 for c in result["cases"]))
        self.assertFalse(run_benchmark("def normalize(x):\n    return x\n")["summary"]["correct"])

    def test_code_boundaries(self):
        validate_code(BASELINE)
        for code in [
            "import os\ndef normalize(x): return x",
            "def normalize(x): return np.load('secret')",
            "def normalize(x): return x.__class__",
            "def normalize(x):\n    np.sum = x\n    return x",
            "def normalize(x): return eval('1')",
            "def normalize(x):\n    while True: pass\n    return x",
        ]:
            with self.assertRaises(ValueError):
                validate_code(code)

    def test_followup_owns_same_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, other = [root / f"{i:012x}" for i in (1, 2, 3)]
            save_run(first, {})
            save_run(second, {"parent_id": first.name})
            save_run(other, {})
            self.assertEqual(session_workspace(first), session_workspace(second))
            self.assertNotEqual(session_workspace(first), session_workspace(other))

class KernelMemoryTest(unittest.TestCase):
    def test_memory_requires_evidence_and_stays_in_session(self):
        import json
        from research_agent.research.kernel import make_kernel_tools
        from research_agent.research.ledger import ResourceLedger
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "000000000001"
            save_run(folder, {"status": "complete"})
            ledger = ResourceLedger(folder)
            tools = make_kernel_tools(None, folder, ledger, None)
            inspect, _, remember = tools
            self.assertIn("error", remember("结论", "边界", "复用原因", ["ffffffff"]))
            (folder / "experiment-ffffffff.json").write_text(json.dumps(
                {"task": "kernel", "status": "completed", "summary": {"correct": False}}))
            result = remember("失败教训", "float32", "避免重复试错", ["ffffffff"])
            self.assertEqual(result["scope"], "session")
            self.assertEqual(inspect()["memory"][0]["lesson"], "失败教训")
            other = Path(directory) / "000000000002"
            save_run(other, {"status": "complete"})
            other_tools = make_kernel_tools(None, other, ResourceLedger(other), None)
            self.assertEqual(other_tools[0]()["memory"], [])
