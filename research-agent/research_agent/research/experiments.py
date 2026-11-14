"""Local experiment tools and the research guidance for each task."""

import json
import os
import platform
import signal
import shlex
import subprocess
import sys
import time
from threading import Lock
from typing import Literal
from uuid import uuid4

from research_agent.research.ledger import RunStopped

CHECKPOINT_PATH = "models/Qwen3-0.6B-4bit"
BENCHMARK_LOCK = Lock()
DEFAULT_TASK = "prefix_cache"
TASK_INSTRUCTIONS = {
    "kernel": (
        "优化 CPU 二维 float32 逐行 L2 归一化算子。先 inspect_kernel_workspace，"
        "读固定基线和数值契约，再自主提出假设并通过 benchmark_kernel 提交代码。"
        "先测基线，改实现、检验数值正确性、对比性能、根据反馈修正；不同方案应有清晰理由。"
        "最终候选必须用 validation 套件复核。不得仅以调用多或运行久作为质量指标。"
        "如果有可复用的成功规律、失败教训或适用边界，由你判断是否调用 remember_kernel_lesson。"
        "只记录实验证据支持的结论，不因耗时长就认为值得沉淀。当前只保存会话记忆。"
        "此任务无需强制联网，优先用基线和实测。每轮决策考虑工具返回的人民币预算。"
    ),
    "prefix_cache": (
        "研究 MLX 前缀缓存。根据首 token 延迟（TTFT）、缓存命中 token 和输出一致性决定补测"
        "不同前缀、反转测量顺序或结束。单次实测只报告该配置下的观察，保留顺序偏差的可能。"
    ),
    "classification": (
        "研究不平衡表格分类。先用 seed 42 比较默认逻辑回归与 class_weight=balanced，"
        "根据少数类召回率、精确率、F1 和误报数判断取舍。若有必要，用另一个划分种子复核。"
        "同一轮两组共享同一份分层划分，标准化只用训练集拟合。复测仍使用同一合成数据集，"
        "测试样本可能重叠。结论限于该合成设置。"
    ),
}


def run_worker(command, root, cancel, timeout_seconds):
    """Stop the entire benchmark process group, including an MLX server."""
    process = subprocess.Popen(command, cwd=root, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + timeout_seconds
    try:
        while process.poll() is None:
            if cancel.wait(0.1):
                raise RunStopped("cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("experiment_timeout")
        if process.returncode:
            raise RuntimeError("experiment_process_failed")
    finally:
        # A child server may outlive a crashed worker, so always clean the group.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def make_experiment(task, root, run_dir, on_event=None, *, ledger, timeout_seconds=180):
    """Bind one local experiment to the run's artifact directory."""
    failures = 0

    def record(details, reason, configuration, command):
        # Serialize measurements and failure accounting, including concurrent tool calls.
        while not BENCHMARK_LOCK.acquire(timeout=0.1):
            ledger.check()
        try:
            return execute_record(details, reason, configuration, command)
        finally:
            BENCHMARK_LOCK.release()

    def execute_record(details, reason, configuration, command):
        nonlocal failures
        ledger.check()
        ledger.stage = "experiment"
        experiment_id = uuid4().hex[:8]
        artifact = run_dir / f"experiment-{experiment_id}.json"
        output = run_dir / f"worker-{experiment_id}.json"
        event = {"experiment_id": experiment_id, "task": task, "reason": reason,
                 "execution": {"kind": "local", "host": platform.node(), "platform": platform.system(),
                               "architecture": platform.machine()}, **details}
        identifier = ledger.start("experiment", **event, configuration=configuration,
                                  retry_after_failures=failures, estimated_cost_cny=0)
        if on_event:
            on_event({"type": "started", **event})
        result = {}
        status = "completed"
        if task == "kernel":
            source = run_dir / f"candidate-{experiment_id}.py"
            source.write_text(configuration["code"])
            command = (f".venv/bin/python -m research_agent.benchmark.row_normalization {shlex.quote(str(source))}"
                       f" --suite {configuration['suite']}")
        try:
            run_worker([sys.executable, "-m", "research_agent.research.worker", task,
                        str(output), json.dumps(configuration)], root, ledger.cancel, min(timeout_seconds, 30) if task == "kernel" else timeout_seconds)
            result = json.loads(output.read_text())
            if "error" in result:
                status = "failed"
            failures = failures + 1 if status == "failed" else 0
        except (RunStopped, KeyboardInterrupt):
            status = "cancelled"
            raise
        except Exception as error:
            status = "timeout" if isinstance(error, TimeoutError) else "failed"
            result = {"error": type(error).__name__}
            failures += 1
        finally:
            output.unlink(missing_ok=True)
            if failures >= 3:
                ledger.stop_reason = "repeated_experiment_failure"
            evidence = {**event, "status": status, "summary": result.get("summary", {}),
                        "artifact": str(artifact), "reproduce_from_project_root": command}
            if "error" in result:
                evidence["error"] = result["error"]
            resources = result.get("resources", {
                "cpu_seconds": None, "peak_process_rss_bytes": None,
                "measurement_scope": "Worker interrupted before resource counters were returned.",
            })
            ledger.finish(identifier, status, artifact=artifact.name, result=evidence["summary"],
                          error=result.get("error"), **resources)
            evidence["resources"] = {**resources, "elapsed_seconds": ledger.entries[identifier]["elapsed_seconds"]}
            if task == "kernel":
                evidence["code"] = configuration["code"]
                evidence["candidate"] = f"candidate-{experiment_id}.py"
                evidence["budget"] = {"max_cost_cny": ledger.max_cost_cny,
                                      "estimated_cost_cny": ledger.summary()["estimated_cost_cny"]}
            artifact.write_text(json.dumps({**result, **evidence}, ensure_ascii=False, indent=2))
            if task == "kernel":
                from research_agent.research.kernel import session_workspace
                (session_workspace(run_dir) / "latest.json").write_text(json.dumps(
                    {"run_id": run_dir.name, "experiment_id": experiment_id, "code": configuration["code"],
                     "summary": evidence["summary"]}, ensure_ascii=False, indent=2))
            if on_event:
                on_event({"type": "completed" if status == "completed" else "experiment_failed", **evidence})
            ledger.stage = "verification"
        return evidence

    def benchmark_prefix_cache(workload: Literal["shared", "different"], reason: str, cache_first: bool = False) -> dict:
        """Compare cache off and on on shared or different prefixes. Explain the experiment choice."""
        command = f".venv/bin/python -m research_agent.benchmark.prefix_cache {CHECKPOINT_PATH} --workload {workload}"
        if cache_first:
            command += " --cache-first"

        configuration = {"model": str(root / CHECKPOINT_PATH), "cache_first": cache_first, "workload": workload}
        return record({"workload": workload, "cache_first": cache_first}, reason, configuration, command)

    def benchmark_classification(reason: str, split_seed: Literal[42, 43, 44] = 42) -> dict:
        """Compare unweighted and balanced logistic regression using one stratified split."""
        command = f".venv/bin/python -m research_agent.benchmark.imbalanced_classification --split-seed {split_seed}"
        return record({"split_seed": split_seed}, reason, {"split_seed": split_seed}, command)

    if task == "kernel":
        from research_agent.research.kernel import make_kernel_tools
        return make_kernel_tools(record, run_dir, ledger, on_event)
    return {"prefix_cache": benchmark_prefix_cache, "classification": benchmark_classification}[task]
