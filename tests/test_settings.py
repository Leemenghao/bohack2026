import copy
import json
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import Mock, patch

import httpx

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from uuid import uuid4

from research_agent import settings, cli
from research_agent.research.ledger import ResourceCallbacks, ResourceLedger
from research_agent.research.decisions import ExperimentDecisions


class SettingsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.vault = {}
        backend = Mock()
        backend.get_password.side_effect = lambda service, account: self.vault.get(account)
        backend.set_password.side_effect = lambda service, account, value: self.vault.update({account: value})
        for name, value in [("SETTINGS_PATH", self.root / "settings.json"), ("ROOT", self.root)]:
            patcher = patch.object(settings, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        for patcher in [patch.object(settings, "keychain", return_value=backend), patch.dict("os.environ", {}, clear=True)]:
            patcher.start(); self.addCleanup(patcher.stop)
        self.payload = copy.deepcopy(settings.DEFAULTS)

    def test_secrets_only_in_vault_and_do_not_cross_endpoint_or_service(self):
        self.payload["model"]["api_key"] = "model-private"
        self.payload["search"]["api_key"] = "search-private"
        public = settings.save_settings(self.payload)
        exposed = json.dumps(public) + settings.SETTINGS_PATH.read_text()
        self.assertNotIn("model-private", exposed)
        self.assertNotIn("search-private", exposed)
        self.assertEqual(settings.runtime_settings()["model"]["api_key"], "model-private")
        self.assertEqual(settings.runtime_settings()["search"]["api_key"], "search-private")
        self.payload["model"].update(base_url="https://other.example/v1", api_key="")
        settings.save_settings(self.payload)
        self.assertEqual(settings.runtime_settings()["model"]["api_key"], "")
        self.assertEqual(settings.SETTINGS_PATH.stat().st_mode & 0o777, 0o600)

    def test_environment_migrates_without_returning_or_changing_original(self):
        env = self.root / ".env"
        env.write_text("DEEPSEEK_API_KEY=existing-private\nAIPING_API_KEY=proxy-private\n")
        self.payload["model"].update(base_url="https://aiping.cn/api/v1", name="provider-model")
        public = settings.save_settings(self.payload)
        self.assertEqual(public["model"]["key_source"], "keychain")
        self.assertNotIn("proxy-private", json.dumps(public))
        self.assertEqual(settings.runtime_settings()["model"]["api_key"], "proxy-private")
        self.assertEqual(settings.runtime_settings()["search"]["api_key"], "existing-private")
        self.assertIn("existing-private", env.read_text())
        self.assertEqual(settings.environment_key("https://aiping.cn.evil.example/v1"), ("", None))

    def test_bad_url_and_partial_pricing_do_not_write_keys(self):
        for url in ("http://remote.example/v1", "https://user:secret@example.com", "https://example.com?key=secret"):
            self.payload["model"]["base_url"] = url
            with self.assertRaises(ValueError): settings.save_settings(self.payload)
        self.payload["model"]["base_url"] = "http://127.0.0.1:8000/v1"
        self.payload["model"]["prices"] = {"input": 1}
        with self.assertRaises(ValueError): settings.save_settings(self.payload)
        self.assertEqual(self.vault, {})

    def test_unknown_proxy_prices_are_not_deepseek_prices(self):
        self.payload["model"]["base_url"] = "https://aiping.cn/api/v1"
        pricing = settings.pricing_for(self.payload)
        self.assertEqual(pricing["models_per_million"], {})
        ledger = ResourceLedger(self.root, pricing=pricing)
        model = Mock(model_name="deepseek-flash", max_tokens=1200)
        snapshot = ExperimentDecisions(ledger, model, 5, None).budget_snapshot()
        self.assertIsNone(snapshot["report_reserve_cny"])
        callback = ResourceCallbacks(ledger)
        identifier = uuid4()
        callback.on_chat_model_start({}, [], run_id=identifier, metadata={"ls_model_name": "deepseek-flash"})
        callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage("ok"))]],
                                     llm_output={"token_usage": {"prompt_tokens": 100, "completion_tokens": 10}}), run_id=identifier)
        self.assertEqual(ledger.summary()["unknown_cost_actions"], 1)

    def test_custom_prices_and_search_endpoint_are_snapshotted(self):
        self.payload["model"]["prices"] = {"input": 1, "output": 2, "cache_read": 0.1}
        self.payload["search"]["base_url"] = "https://search.example/tools"
        prices = settings.pricing_for(self.payload)
        self.assertEqual(prices["models_per_million"]["deepseek-flash"]["input"], 1)
        self.assertIsNone(prices["search_per_request"])

    def test_agent_uses_configured_endpoint_and_model_without_deepseek_options(self):
        self.payload["model"].update(base_url="https://aiping.cn/api/v1", name="custom-model", api_key="private")
        self.payload["search"]["api_key"] = "separate-private"
        agent = Mock()
        agent.invoke.return_value = {"messages": [AIMessage("done")]}
        with patch.object(cli, "runtime_settings", return_value=self.payload), patch.object(cli, "ChatOpenAI") as model, patch.object(cli, "build_agent", return_value=agent):
            result = cli.run_research("test", self.root / "run", use_memory=False, budget_aware=False)
        self.assertEqual(model.call_args.kwargs["base_url"], "https://aiping.cn/api/v1")
        self.assertEqual(model.call_args.kwargs["model"], "custom-model")
        self.assertIsNone(model.call_args.kwargs["extra_body"])
        self.assertEqual(result["model"], "custom-model")
        for file in (self.root / "run").glob("*"):
            self.assertNotIn("private", file.read_text())

    def test_http_settings_reject_foreign_origin_and_never_return_keys(self):
        from research_agent.web_server import Handler
        with patch.object(Handler, "log_message"), ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                self.payload["model"]["api_key"] = "http-private-key"
                with httpx.Client(trust_env=False) as client:
                    denied = client.post(base + "/api/settings", json=self.payload, headers={"Origin": "https://other.example"})
                    self.assertEqual(denied.status_code, 403)
                    self.assertEqual(self.vault, {})
                    saved = client.post(base + "/api/settings", json=self.payload, headers={"Origin": base})
                    self.assertEqual(saved.status_code, 200)
                    self.assertNotIn("http-private-key", saved.text)
                    self.assertNotIn("http-private-key", client.get(base + "/api/settings").text)
            finally:
                server.shutdown()
                thread.join()
