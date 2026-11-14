"""Local experiment tools and the research guidance for each task."""

import json
from threading import Lock
from typing import Literal
from uuid import uuid4

from benchmark.prefix_cache import run_benchmark as run_prefix_cache

CHECKPOINT_PATH = "models/Qwen3-0.6B-4bit"
BENCHMARK_LOCK = Lock()
DEFAULT_TASK = "prefix_cache"
TASK_INSTRUCTIONS = {
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


def make_experiment(task, root, run_dir, on_event=None):
    """Bind one local experiment to the run's artifact directory."""
    def record(details, reason, run, command):
        experiment_id = uuid4().hex[:8]
        artifact = run_dir / f"experiment-{experiment_id}.json"
        event = {"experiment_id": experiment_id, "task": task, "reason": reason, **details}
        if on_event:
            on_event({"type": "started", **event})
        result = run()
        evidence = {
            **event,
            "summary": result["summary"],
            "artifact": str(artifact),
            "reproduce_from_project_root": command,
        }
        artifact.write_text(json.dumps({**result, **evidence}, ensure_ascii=False, indent=2))
        if on_event:
            on_event({"type": "completed", **evidence})
        return evidence

    def benchmark_prefix_cache(workload: Literal["shared", "different"], reason: str, cache_first: bool = False) -> dict:
        """Compare cache off and on on shared or different prefixes. Explain the experiment choice."""
        command = f".venv/bin/python benchmark/prefix_cache.py {CHECKPOINT_PATH} --workload {workload}"
        if cache_first:
            command += " --cache-first"

        def run():
            checkpoint = root / CHECKPOINT_PATH
            with BENCHMARK_LOCK:
                result = run_prefix_cache(str(checkpoint), cache_first=cache_first, workload=workload)
            return {"summary": result["summary"][workload], "requests": result["runs"]}

        return record({"workload": workload, "cache_first": cache_first}, reason, run, command)

    def benchmark_classification(reason: str, split_seed: Literal[42, 43, 44] = 42) -> dict:
        """Compare unweighted and balanced logistic regression using one stratified split."""
        from benchmark.imbalanced_classification import run_benchmark

        command = f".venv/bin/python benchmark/imbalanced_classification.py --split-seed {split_seed}"
        return record({"split_seed": split_seed}, reason, lambda: run_benchmark(split_seed), command)

    return {"prefix_cache": benchmark_prefix_cache, "classification": benchmark_classification}[task]
