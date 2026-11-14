import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from langchain_core.messages import AIMessage
from research_agent.conversation_store import ConversationStore
from research_agent.research.history import make_history_tools, summarize_session
from research_agent.research.ledger import ResourceLedger
from research_agent.runview import save_run


class HistoryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.first, self.other = [self.root / f"{i:012x}" for i in (1, 2)]
        for folder in (self.first, self.other):
            save_run(folder, {"question": "Kernel research", "status": "complete", "task": "kernel", "created_at": "2026-11-15"})
        self.store = ConversationStore(self.root)
        self.store.save_summary(self.first.name, self.first.name, "Normalization was verified on three shapes", "2026-11-15", "test")
        (self.first / "report.md").write_text("Measured evidence")
        self.ledger = ResourceLedger(self.other)
        self.search, self.read = make_history_tools(self.other, self.ledger)

    def test_private_sessions_and_revocation_are_enforced_per_read(self):
        self.assertEqual(self.search("Normalization"), [])
        self.assertIn("error", self.read(self.first.name))
        self.store.update_session(self.first.name, shared=True)
        self.assertEqual(len(self.search("Normalization")), 1)
        self.assertEqual(self.read(self.first.name, self.first.name, "report.md")["content"], "Measured evidence")
        self.store.update_session(self.first.name, shared=False)
        self.assertIn("error", self.read(self.first.name, self.first.name, "report.md"))

    def test_reads_cannot_escape_session_or_follow_symlinks(self):
        self.store.update_session(self.first.name, shared=True)
        self.assertIn("error", self.read(self.first.name, self.other.name, "report.md"))
        self.assertIn("error", self.read(self.first.name, self.first.name, "../.env"))
        path = self.first / "candidate-12345678.py"
        path.symlink_to(self.other / "run.json")
        self.assertIn("error", self.read(self.first.name, self.first.name, path.name))

    def test_model_summary_is_saved_with_provenance_and_default_privacy(self):
        model = Mock(model_name="test-model")
        model.bind.return_value.invoke.return_value = AIMessage("Verified on three shapes. Larger inputs remain untested.")
        summary = summarize_session(model, self.other, "question", "report", "prior", self.ledger, {})
        self.assertEqual(summary["origin"], "agent")
        self.assertEqual(summary["source_run_id"], self.other.name)
        stored = self.store.session_summary(self.other.name)
        self.assertFalse(stored["shared"])
        self.assertIn("untested", stored["content"])
        self.assertEqual(model.bind.return_value.invoke.call_args.kwargs["config"]["metadata"]["resource_purpose"], "session_summary")

    def test_invalid_model_output_does_not_replace_summary(self):
        model = Mock(model_name="test-model")
        model.bind.return_value.invoke.return_value = AIMessage("<DSML tool-call>")
        with self.assertRaises(ValueError):
            summarize_session(model, self.other, "question", "report", "", self.ledger, {})
        self.assertIsNone(self.store.session_summary(self.other.name)["content"])

class SummaryBudgetTest(unittest.TestCase):
    def run_turn(self, budget, *, fail_summary=False, mode="chat"):
        import copy
        from uuid import uuid4
        from langchain_core.outputs import ChatGeneration, LLMResult
        from research_agent import cli, settings
        from unittest.mock import patch
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name) / "000000000001"
        save_run(folder, {"question": "question", "status": "running", "task": "kernel", "created_at": "2026-11-15"})
        connection = copy.deepcopy(settings.DEFAULTS)
        connection["model"]["api_key"] = "test-only-key"
        model = Mock(model_name=connection["model"]["name"])
        model.bind.return_value = model

        def invoke(messages, config):
            if fail_summary and model.invoke.call_count > 1:
                raise RuntimeError("summary failed")
            message = AIMessage("Verified answer", usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25})
            identifier = uuid4()
            for callback in config["callbacks"]:
                callback.on_chat_model_start({}, [], run_id=identifier,
                    metadata={"ls_model_name": model.model_name, **config.get("metadata", {})})
                callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=identifier)
            return message

        model.invoke.side_effect = invoke
        with patch.object(cli, "runtime_settings", return_value=connection), patch.object(cli, "ChatOpenAI", return_value=model):
            result = cli.run_research("question", folder, task="kernel", use_memory=False, mode=mode, cloud_budget=budget)
        return result, folder

    def test_summary_is_metered_and_one_call_budget_skips_it(self):
        import json
        complete, folder = self.run_turn(2)
        self.assertEqual(complete["session_summary_status"], "complete")
        self.assertEqual(complete["resources"]["model_calls"], 2)
        ledger = json.loads((folder / "resources.json").read_text())
        summary = [e for e in ledger["entries"] if e.get("purpose") == "session_summary"]
        self.assertEqual(len(summary), 1)
        self.assertGreater(summary[0]["estimated_cost_cny"], 0)
        limited, folder = self.run_turn(1)
        self.assertEqual(limited["session_summary_status"], "budget_skipped")
        self.assertEqual(limited["resources"]["model_calls"], 1)
        self.assertFalse((folder / "session-summary.json").exists())

    def test_summary_failure_preserves_answer_and_explicit_summary_is_not_repeated(self):
        failed, folder = self.run_turn(2, fail_summary=True)
        self.assertEqual(failed["status"], "complete")
        self.assertEqual(failed["session_summary_status"], "failed")
        self.assertIn("Verified answer", (folder / "report.md").read_text())
        explicit, folder = self.run_turn(1, mode="summary")
        self.assertEqual(explicit["session_summary_status"], "complete")
        self.assertEqual(explicit["resources"]["model_calls"], 1)
