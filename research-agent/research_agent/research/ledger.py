"""Durable, per-run resource accounting. Prices are estimates, never invoices."""

import json
import resource
import sys
import time
from datetime import datetime, timezone
from threading import Event, RLock
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler


PRICING = {
    "version": "deepseek-cny-2026-11-14",
    "source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
    "currency": "CNY",
    "basis": "高峰刊例价估算；空闲时段、赠送额度和实际账单可能更低",
    "models_per_million": {
        "deepseek-flash": {"cache_read": 0.04, "input": 2.0, "output": 8.0},
        "deepseek-v4-pro": {"cache_read": 0.30, "input": 9.0, "output": 27.0},
    },
    "search_per_request": 0.005,
    "fetch_per_request": 0.005,
}


class RunStopped(Exception):
    """A user cancellation, resource threshold or repeated experiment failure."""


class ResourceLedger:
    def __init__(self, run_dir, *, cancel=None, max_cost_cny=None, on_event=None, pricing=None):
        self.pricing = pricing if pricing is not None else PRICING
        self.path = run_dir / "resources.json"
        self.cancel = cancel or Event()
        self.max_cost_cny = max_cost_cny
        self.on_event = on_event
        self.stage = "plan"
        self.stop_reason = ""
        self.entries = {}
        self.started = time.monotonic()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        self.initial_cpu = usage.ru_utime + usage.ru_stime
        self.starts = {}
        self.lock = RLock()
        self.status = "running"
        self._save()

    def check(self):
        if self.cancel.is_set():
            raise RunStopped("cancelled")
        if self.stop_reason:
            raise RunStopped(self.stop_reason)
        if self.max_cost_cny is not None and self.summary()["estimated_cost_cny"] >= self.max_cost_cny:
            raise RunStopped("cost_limit")

    def start(self, kind, *, check=True, **details):
        with self.lock:
            if check:
                self.check()
            identifier = uuid4().hex
            self.starts[identifier] = time.monotonic()
            self.entries[identifier] = {
                "id": identifier, "kind": kind, "stage": self.stage,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "running", "estimated_cost_cny": None, **details,
            }
            self._save()
            return identifier

    def finish(self, identifier, status="completed", **details):
        with self.lock:
            entry = self.entries[identifier]
            if entry["status"] != "running":
                return
            entry.update(status=status, elapsed_seconds=round(time.monotonic() - self.starts[identifier], 4), **details)
            self._save()

    def summary(self):
        with self.lock:
            rows = list(self.entries.values())
            stages = {}
            for row in rows:
                stage = stages.setdefault(row["stage"], {"actions": 0, "estimated_cost_cny": 0, "action_seconds": 0})
                stage["actions"] += 1
                stage["estimated_cost_cny"] += row.get("estimated_cost_cny") or 0
                stage["action_seconds"] += row.get("elapsed_seconds", 0)
            for stage in stages.values():
                stage["estimated_cost_cny"] = round(stage["estimated_cost_cny"], 8)
                stage["action_seconds"] = round(stage["action_seconds"], 4)
            models = [row for row in rows if row["kind"] == "model"]
            experiments = [row for row in rows if row["kind"] == "experiment"]
            process = resource.getrusage(resource.RUSAGE_SELF)
            return {
                "currency": "CNY", "status": self.status,
                "stop_reason": self.stop_reason or None,
                "estimated_cost_cny": round(sum(row.get("estimated_cost_cny") or 0 for row in rows), 8),
                "max_cost_cny": self.max_cost_cny,
                "unknown_cost_actions": sum(row.get("estimated_cost_cny") is None for row in rows
                                            if row["kind"] in ("model", "search", "fetch")),
                "model_calls": len(models),
                "usage": {name: sum(row.get(name) or 0 for row in models)
                          for name in ("input_tokens", "output_tokens", "cached_tokens")},
                "search_requests": sum(row["kind"] == "search" for row in rows),
                "fetch_requests": sum(row["kind"] == "fetch" for row in rows),
                "billable_requests": sum(row.get("billable_requests") or 0 for row in rows),
                "experiments": sum(row["kind"] == "experiment" for row in rows),
                "failed_experiments": sum(row["kind"] == "experiment" and row["status"] in ("failed", "timeout") for row in rows),
                "elapsed_seconds": round(time.monotonic() - self.started, 2),
                "local_resources": {
                    "experiment_cpu_seconds": round(sum(row.get("cpu_seconds") or 0 for row in experiments), 4),
                    "experiments_without_cpu_measurement": sum(row.get("cpu_seconds") is None for row in experiments),
                    "max_experiment_process_rss_bytes": max((row.get("peak_process_rss_bytes") or 0 for row in experiments), default=0) or None,
                    "host_process_cpu_seconds": round(process.ru_utime + process.ru_stime - self.initial_cpu, 4),
                    "host_process_lifetime_peak_rss_bytes": int(process.ru_maxrss * (1 if sys.platform == "darwin" else 1024)),
                    "scope": "Host CPU covers this process during the run, including HTTP work; host RSS covers process lifetime. Experiment RSS is the maximum single-process peak, not a process-tree sum.",
                },
                "stages": stages,
                "unmetered": ["本机电费", "GPU 能耗", "硬件折旧"],
                "notes": [self.pricing["basis"], "本地动作费用为新增 API 费用，不代表本机运行没有成本。",
                          "阶段 action_seconds 为各动作耗时之和，并行时不等于整次运行耗时。",
                          "金额阈值在动作开始前检查，已发出的请求仍会结算，可能超过阈值。"],
            }

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = self.summary()
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"pricing": self.pricing, "summary": snapshot,
                                         "entries": list(self.entries.values())}, ensure_ascii=False, indent=2))
        temporary.replace(self.path)
        if self.on_event:
            self.on_event({"type": "resources", **snapshot})

    def close(self, status):
        with self.lock:
            self.status = status
            for identifier, row in self.entries.items():
                if row["status"] == "running":
                    self.finish(identifier, "interrupted")
            self._save()
            return self.summary()


class ResourceCallbacks(BaseCallbackHandler):
    """Invocation callbacks propagate to nested agents and summarization calls."""

    raise_error = True
    run_inline = True

    def __init__(self, ledger):
        self.ledger = ledger
        self.calls = {}
        self.tools = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, metadata=None, **kwargs):
        metadata = metadata or {}
        model = metadata.get("ls_model_name") or kwargs.get("invocation_params", {}).get("model", "unknown")
        self.calls[run_id] = self.ledger.start(
            "model", model=model, purpose=metadata.get("resource_purpose", self.ledger.stage),
            parent_run_id=str(parent_run_id), node=metadata.get("langgraph_node"),
        )

    def on_llm_end(self, response, *, run_id, **kwargs):
        identifier = self.calls.pop(run_id, None)
        if identifier is None:
            return
        raw = (response.llm_output or {}).get("token_usage") or {}
        message = response.generations[0][0].message if response.generations and response.generations[0] else None
        usage = getattr(message, "usage_metadata", None) or {}
        inputs = raw.get("prompt_tokens", usage.get("input_tokens"))
        outputs = raw.get("completion_tokens", usage.get("output_tokens"))
        cached = raw.get("prompt_cache_hit_tokens", (raw.get("prompt_tokens_details") or {}).get(
            "cached_tokens", (usage.get("input_token_details") or {}).get("cache_read")))
        entry = self.ledger.entries[identifier]
        rates = self.ledger.pricing["models_per_million"].get(entry["model"])
        cost = None
        if rates and inputs is not None and outputs is not None:
            # Missing cache details are conservatively priced as uncached input.
            hit = min(inputs, max(0, cached or 0))
            cost = round(((inputs - hit) * rates["input"] + hit * rates["cache_read"] + outputs * rates["output"]) / 1_000_000, 8)
        self.ledger.finish(identifier, input_tokens=inputs, output_tokens=outputs, cached_tokens=cached,
                           estimated_cost_cny=cost, usage_available=inputs is not None and outputs is not None,
                           cache_usage_available=cached is not None)

    def on_llm_error(self, error, *, run_id, **kwargs):
        identifier = self.calls.pop(run_id, None)
        if identifier:
            self.ledger.finish(identifier, "failed", error=type(error).__name__, usage_available=False)

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        name = (serialized or {}).get("name", "tool")
        self.ledger.check()
        # These tools record their own provider billing / experiment metrics.
        if name in ("web_search", "fetch_source", "search_sources") or name.startswith("benchmark_"):
            return
        self.tools[run_id] = self.ledger.start("tool", name=name, estimated_cost_cny=0)

    def on_tool_end(self, output, *, run_id, **kwargs):
        identifier = self.tools.pop(run_id, None)
        if identifier:
            self.ledger.finish(identifier)

    def on_tool_error(self, error, *, run_id, **kwargs):
        identifier = self.tools.pop(run_id, None)
        if identifier:
            self.ledger.finish(identifier, "failed", error=type(error).__name__)
