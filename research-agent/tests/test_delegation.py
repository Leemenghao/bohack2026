import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from research_agent.research.delegation import make_delegate_tool, routing_decision
from research_agent.research.ledger import ResourceLedger, RunStopped


class DelegationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.ledger = ResourceLedger(self.folder, max_cost_cny=1, max_model_calls=8)
        self.low = Mock(model_name="deepseek-flash", max_tokens=1200)
        self.high = Mock(model_name="deepseek-v4-pro", max_tokens=1200)
        self.low.invoke.return_value = self.high.invoke.return_value = AIMessage("review with evidence")
        self.evidence = [{"status": "completed", "summary": {"correct": False}}] * 2

    def route(self, **kwargs):
        return routing_decision(self.ledger, self.low, self.high, trigger="failed_experiments",
                                evidence=self.evidence, context_chars=2000, call_limit=8, **kwargs)

    def test_upgrade_downgrade_and_report_reserve(self):
        self.assertEqual(self.route()["model"], "deepseek-v4-pro")
        self.ledger.max_cost_cny = .06
        self.assertEqual(self.route()["model"], "deepseek-flash")
        self.assertTrue(self.route()["allowed"])
        self.ledger.max_cost_cny = .01
        self.assertFalse(self.route()["allowed"])
        self.ledger.max_cost_cny = 1
        identifier = self.ledger.start("model", model="unknown")
        self.ledger.finish(identifier)
        self.assertFalse(self.route()["allowed"])

    def test_all_nested_calls_share_one_limit(self):
        for _ in range(8):
            identifier = self.ledger.start("model")
            self.ledger.finish(identifier, estimated_cost_cny=0)
        with self.assertRaisesRegex(RunStopped, "call_limit"):
            self.ledger.start("model")
        self.assertFalse(self.route()["allowed"])

    def test_tool_schema_callback_context_and_artifact_scope(self):
        delegate = make_delegate_tool(self.low, self.high, self.folder, self.ledger, 8)
        tool = StructuredTool.from_function(delegate)
        self.assertNotIn("config", tool.tool_call_schema.model_fields)
        for i, evidence in enumerate(self.evidence):
            (self.folder / f"experiment-{i:08x}.json").write_text(json.dumps(evidence))
        result = tool.invoke({"role": "review", "task": "diagnose failures", "artifacts": ["experiment-00000000.json", "experiment-00000001.json"], "trigger": "failed_experiments"})
        self.assertEqual(result["routing"]["model"], "deepseek-v4-pro")
        self.assertEqual(self.high.invoke.call_args.kwargs["config"]["metadata"]["resource_purpose"], "specialist:review")
        self.assertEqual(len(list(self.folder.glob("delegation-*.json"))), 1)
        bad = delegate("code", "read files", ["../../.env"], {})
        self.assertIn("error", bad)
        self.ledger.cancel.set()
        with self.assertRaisesRegex(RunStopped, "cancelled"):
            delegate("code", "new task", [], {})

    def test_single_record_does_not_trigger_expensive_review(self):
        self.evidence.pop()
        self.assertEqual(self.route()["model"], "deepseek-flash")

    def test_measured_rank_reversal_escalates_routine_review_only(self):
        self.evidence = [{"summary": {"correct": True, "code_sha256": str(i), "cases": [
            {"shape": [32, 32], "layout": "contiguous", "candidate_ms": times[0]},
            {"shape": [512, 512], "layout": "strided", "candidate_ms": times[1]},
        ]}} for i, times in enumerate(([1, 3], [2, 2]))]
        result = routing_decision(self.ledger, self.low, self.high, trigger="routine", evidence=self.evidence,
                                  context_chars=2000, call_limit=8)
        self.assertEqual(result["model"], "deepseek-v4-pro")
        self.assertIn("排名反转", result["reason"])
        self.assertEqual(self.route(allow_review=False)["model"], "deepseek-flash")

class CompactEvidenceTest(unittest.TestCase):
    def test_model_context_keeps_noise_and_preserves_original_samples(self):
        from research_agent.research.evidence import compact_evidence
        record = {'summary': {'cases': [{'correct': True, 'candidate_ms': 2,
                   'samples_ms': {'candidate': [1, 2, 100]}}]}}
        compact = compact_evidence(record)
        self.assertEqual(compact['summary']['cases'][0]['candidate_mad_ms'], 1)
        self.assertNotIn('samples_ms', compact['summary']['cases'][0])
        self.assertEqual(record['summary']['cases'][0]['samples_ms']['candidate'], [1, 2, 100])
