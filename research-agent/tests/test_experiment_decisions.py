import json
import tempfile
import unittest
from pathlib import Path

from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from research_agent.research.decisions import ExperimentDecisions
from research_agent.research.ledger import ResourceLedger


@tool
def record_experiment_decision() -> str:
    """Record what to do next."""
    return ""


@tool
def benchmark_classification() -> str:
    """Run a local experiment."""
    return ""


class ExperimentDecisionsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.ledger = ResourceLedger(self.folder, max_cost_cny=0.12)
        model = ChatOpenAI(model="deepseek-flash", api_key="test", max_tokens=1200)
        self.events = []
        self.decisions = ExperimentDecisions(self.ledger, model, 15, self.events.append)
        self.decisions.latest = {"experiment_id": "abcd1234"}
        (self.folder / "experiment-abcd1234.json").write_text(json.dumps({
            "experiment_id": "abcd1234", "status": "completed", "reason": "Check recall",
            "summary": {"recall": 0.48}, "reproduce_from_project_root": "run --split-seed 42",
        }))
        self.request = ModelRequest(
            model=model, system_message=SystemMessage("Use the tools to research."),
            messages=[HumanMessage("Question"), ToolMessage("Old tool context", tool_call_id="test")],
            tools=[record_experiment_decision, benchmark_classification],
        )

    def next_request(self):
        return self.decisions.wrap_model(self.request, lambda request: request)

    def test_decision_immediately_runs_followup_with_selected_parameters(self):
        request = self.next_request()
        self.assertEqual(request.tool_choice, "record_experiment_decision")
        self.assertIn("remaining_cost_cny", request.messages[0].text)
        self.assertIn("abcd1234", request.messages[0].text)
        self.assertNotIn("Old tool context", request.messages[0].text)
        calls = []

        def experiment(**kwargs):
            calls.append(kwargs)
            self.decisions.latest = {"experiment_id": "next1234"}
            return {"status": "completed", "experiment_id": "next1234"}

        result = self.decisions.apply(experiment, "retest", "Recall improved", "Test another split",
                                      {"split_seed": 43})
        self.assertEqual(result["experiment_id"], "next1234")
        self.assertEqual(calls, [{"reason": "Recall improved", "split_seed": 43}])
        self.assertEqual(self.next_request().tool_choice, "record_experiment_decision")
        self.assertEqual(self.events[0]["experiment_ids"], ["abcd1234"])
        self.assertEqual(self.events[0]["parameters"], {"split_seed": 43})

    def test_tight_budget_uses_saved_evidence_instead_of_tool_history(self):
        self.ledger.max_cost_cny = 0.015
        request = self.next_request()
        self.assertEqual(request.tools, [])
        self.assertEqual(len(request.messages), 1)
        self.assertIn("abcd1234", request.messages[0].text)
        self.assertIn("0.48", request.messages[0].text)
        self.assertNotIn("Old tool context", request.messages[0].text)
        self.assertEqual(self.events[0]["origin"], "budget_guard")

    def test_budget_is_rechecked_after_model_chooses_retest(self):
        charge = self.ledger.start("model", input_tokens=3000)
        self.ledger.finish(charge, estimated_cost_cny=0.11)
        self.decisions.apply(lambda **kwargs: self.fail("Follow-up should not run"),
                             "retest", "Recall improved", "Test another split", {"split_seed": 43})
        self.assertEqual(self.next_request().tools, [])
        self.assertEqual([event["action"] for event in self.events], ["finish"])

    def test_report_distinguishes_saved_memory_from_tool_intent(self):
        request = self.decisions.report_request(self.request)
        self.assertIn('"saved_session_memories": []', request.messages[0].text)
        (self.folder / "memory-12345678.json").write_text(json.dumps({"lesson": "Measured result"}))
        request = self.decisions.report_request(self.request)
        self.assertIn("Measured result", request.messages[0].text)
        self.assertNotIn("Old tool context", request.messages[0].text)
        self.assertEqual(request.tools, [])
