"""Resource accounting and stop paths; no paid APIs are used here."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event, Timer
from unittest.mock import patch
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI

from research_agent.archive import build_archive
from research_agent.memory import load_previous
from research_agent import cli
from research_agent.research.experiments import make_experiment, run_worker
from research_agent.research.ledger import ResourceCallbacks, ResourceLedger, RunStopped
from research_agent.research.sources import _deepseek_request
from research_agent.runview import load_run


class ResourceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.ledger = ResourceLedger(self.folder)
        connection = {"model": {"base_url": "https://api.deepseek.com", "name": "deepseek-flash", "api_key": "test", "prices": None},
                      "search": {"base_url": "https://api.deepseek.com/v1/tools", "api_key": "search-test"}}
        self.settings_patch = patch.object(cli, "runtime_settings", return_value=connection)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def model_call(self, raw=None, model="deepseek-flash"):
        callback = ResourceCallbacks(self.ledger)
        identifier = uuid4()
        callback.on_chat_model_start({}, [], run_id=identifier, metadata={"ls_model_name": model})
        response = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="done"))]],
                             llm_output={"token_usage": raw} if raw else {})
        callback.on_llm_end(response, run_id=identifier)
        return list(self.ledger.entries.values())[-1]

    def test_cny_cache_and_thinking_are_not_double_counted(self):
        entry = self.model_call({"prompt_tokens": 1000, "prompt_cache_hit_tokens": 600,
                                 "completion_tokens": 100, "completion_tokens_details": {"reasoning_tokens": 50}})
        self.assertAlmostEqual(entry["estimated_cost_cny"], 0.001624)
        self.assertEqual(entry["cached_tokens"], 600)
        self.assertEqual(entry["output_tokens"], 100)
        self.assertEqual(json.loads((self.folder / "resources.json").read_text())["summary"]["model_calls"], 1)

    def test_missing_usage_or_unknown_model_is_not_zero_cost(self):
        self.assertIsNone(self.model_call()["estimated_cost_cny"])
        self.assertIsNone(self.model_call({"prompt_tokens": 10, "completion_tokens": 5}, "unknown")["estimated_cost_cny"])
        self.assertEqual(self.ledger.summary()["unknown_cost_actions"], 2)

    def test_model_failure_is_durable_and_does_not_store_exception_text(self):
        callback = ResourceCallbacks(self.ledger)
        identifier = uuid4()
        callback.on_chat_model_start({}, [], run_id=identifier)
        callback.on_llm_error(RuntimeError("secret-request-data"), run_id=identifier)
        content = (self.folder / "resources.json").read_text()
        self.assertNotIn("secret-request-data", content)
        self.assertEqual(self.ledger.summary()["unknown_cost_actions"], 1)

    def test_nested_model_calls_inherit_callbacks(self):
        def response(request):
            return httpx.Response(200, json={
                "id": "test", "model": "deepseek-flash", "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop", "index": 0}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23},
            })
        client = httpx.Client(transport=httpx.MockTransport(response))
        self.addCleanup(client.close)
        model = ChatOpenAI(model="deepseek-flash", api_key="test", http_client=client, max_retries=0)
        child = RunnableLambda(lambda value: model.invoke(value))
        parent = RunnableLambda(lambda value: [model.invoke(value), child.invoke(value)])
        parent.invoke("test", config={"callbacks": [ResourceCallbacks(self.ledger)]})
        self.assertEqual(self.ledger.summary()["model_calls"], 2)
        self.assertEqual(self.ledger.summary()["usage"]["input_tokens"], 40)
        self.assertEqual(self.ledger.summary()["unknown_cost_actions"], 0)

    def test_search_bills_results_once_and_empty_or_http_error_zero(self):
        for content, expected in [({"results": [{"url": "https://example.com"}]}, 0.005), ({"results": []}, 0)]:
            response = httpx.Response(200, json=content, request=httpx.Request("POST", "https://example.com"))
            with patch("httpx.post", return_value=response):
                _deepseek_request("search", "not-saved", {"query": "test"}, self.ledger)
            self.assertEqual(list(self.ledger.entries.values())[-1]["estimated_cost_cny"], expected)
        with patch("httpx.post", return_value=httpx.Response(429, request=httpx.Request("POST", "https://example.com"))):
            with self.assertRaises(httpx.HTTPStatusError):
                _deepseek_request("fetch", "not-saved", {"url": "https://example.com"}, self.ledger)
        self.assertEqual(self.ledger.summary()["estimated_cost_cny"], 0.005)
        self.assertEqual(self.ledger.summary()["billable_requests"], 1)
        self.assertNotIn("not-saved", (self.folder / "resources.json").read_text())

    def test_budget_and_cancel_prevent_new_actions(self):
        self.ledger.max_cost_cny = 0.001
        self.model_call({"prompt_tokens": 1000, "completion_tokens": 100})
        with self.assertRaisesRegex(RunStopped, "cost_limit"):
            self.ledger.start("model")
        self.ledger.cancel.set()
        with self.assertRaisesRegex(RunStopped, "cancelled"):
            self.ledger.start("experiment")
        self.assertEqual(len(self.ledger.entries), 1)

    def experiment(self):
        return make_experiment("classification", Path.cwd(), self.folder, ledger=self.ledger)

    def test_experiments_have_no_three_run_cap(self):
        def complete(command, *args):
            Path(command[4]).write_text(json.dumps({"summary": {"metric": 1}, "resources": {"cpu_seconds": 0.1, "peak_process_rss_bytes": 100}}))
        experiment = self.experiment()
        with patch("research_agent.research.experiments.run_worker", side_effect=complete):
            for _ in range(4):
                self.assertEqual(experiment("verify")["status"], "completed")
        self.assertEqual(self.ledger.summary()["experiments"], 4)
        self.assertAlmostEqual(self.ledger.summary()["local_resources"]["experiment_cpu_seconds"], 0.4)

    def test_timeouts_record_artifacts_and_three_failures_stop(self):
        experiment = self.experiment()
        with patch("research_agent.research.experiments.run_worker", side_effect=TimeoutError):
            for _ in range(3):
                result = experiment("verify")
                self.assertEqual(result["status"], "timeout")
                self.assertTrue(Path(result["artifact"]).is_file())
                self.assertIsNone(result["resources"]["cpu_seconds"])
            with self.assertRaisesRegex(RunStopped, "repeated_experiment_failure"):
                experiment("retry")
        self.assertEqual(self.ledger.summary()["failed_experiments"], 3)

    def test_cancelled_experiment_keeps_record(self):
        with patch("research_agent.research.experiments.run_worker", side_effect=RunStopped("cancelled")):
            with self.assertRaises(RunStopped):
                self.experiment()("verify")
        record = json.loads(next(self.folder.glob("experiment-*.json")).read_text())
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(self.ledger.summary()["experiments"], 1)

    def test_keyboard_interrupt_does_not_mark_experiment_completed(self):
        with patch("research_agent.research.experiments.run_worker", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.experiment()("verify")
        record = json.loads(next(self.folder.glob("experiment-*.json")).read_text())
        self.assertEqual(record["status"], "cancelled")

    def test_subprocess_timeout_kills_descendants(self):
        marker = self.folder / "orphan.txt"
        child = f"import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).write_text('orphan')"
        parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
        with self.assertRaises(TimeoutError):
            run_worker([sys.executable, "-c", parent], Path.cwd(), Event(), 0.2)
        time.sleep(1)
        self.assertFalse(marker.exists())

    def test_running_subprocess_can_be_cancelled(self):
        cancel = Event()
        timer = Timer(0.2, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaisesRegex(RunStopped, "cancelled"):
            run_worker([sys.executable, "-c", "import time; time.sleep(30)"], Path.cwd(), cancel, 10)

    def test_failed_run_saves_usage_and_report_and_is_not_memory(self):
        class FailingAgent:
            def invoke(inner, data, config):
                callback = config["callbacks"][0]
                identifier = uuid4()
                callback.on_chat_model_start({}, [], run_id=identifier)
                callback.on_llm_error(RuntimeError("private"), run_id=identifier)
                raise RuntimeError("private")
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test"}), patch.object(cli, "build_agent", return_value=FailingAgent()):
            with self.assertRaises(RuntimeError):
                cli.run_research("test", self.folder, use_memory=False)
        result = load_run(self.folder, include_detail=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["resources"]["model_calls"], 1)
        self.assertIn("未完成", result["result"]["report"])
        self.assertNotIn("private", result["result"]["report"])
        history = self.folder / "history"
        failed = history / "failed"
        failed.mkdir(parents=True)
        (failed / "report.md").write_text("incomplete")
        (failed / "summary.json").write_text('{"status": "failed"}')
        self.assertIsNone(load_previous(history))
        self.assertIn(b"resources.json", build_archive(self.folder))

    def test_precancelled_run_returns_cancelled_without_model(self):
        cancel = Event()
        cancel.set()
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test"}), patch.object(cli, "build_agent") as build:
            result = cli.run_research("test", self.folder, use_memory=False, cancel=cancel)
        build.assert_not_called()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(load_run(self.folder, include_detail=True)["status"], "cancelled")

    def test_final_response_is_kept_when_last_call_crosses_cost_threshold(self):
        class FinishingAgent:
            def invoke(inner, data, config):
                callback = config["callbacks"][0]
                identifier = uuid4()
                callback.on_chat_model_start({}, [], run_id=identifier, metadata={"ls_model_name": "deepseek-flash"})
                message = AIMessage(content="Verified conclusion")
                callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]],
                                               llm_output={"token_usage": {"prompt_tokens": 1000, "completion_tokens": 100}}), run_id=identifier)
                return {"messages": [message]}
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test"}), patch.object(cli, "build_agent", return_value=FinishingAgent()):
            result = cli.run_research("test", self.folder, use_memory=False, max_cost_cny=0.001)
        self.assertEqual(result["status"], "complete")
        self.assertIn("Verified conclusion", result["report"])
        self.assertIn("resources.json", result["artifacts"])
        self.assertIn("report.md", result["artifacts"])

    def test_model_call_limit_is_a_stop_not_a_successful_conclusion(self):
        class LimitedAgent:
            def invoke(inner, data, config):
                raise cli.ModelCallLimitExceededError(thread_count=1, run_count=1, thread_limit=None, run_limit=1)
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test"}), patch.object(cli, "build_agent", return_value=LimitedAgent()):
            result = cli.run_research("test", self.folder, use_memory=False)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["resources"]["stop_reason"], "call_limit")


if __name__ == "__main__":
    unittest.main()
