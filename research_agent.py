import argparse
import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from dotenv import load_dotenv
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from benchmark.prefix_cache import run_benchmark

ROOT = Path(__file__).resolve().parent
CHECKPOINT = ROOT / "models" / "Qwen3-0.6B-4bit"
BENCHMARK_LOCK = Lock()
MODEL = "deepseek-flash"
INSTRUCTIONS = """
你是研究推理性能的 Research Agent。根据用户问题提出可检验的假设，
调用本机 benchmark 获取真实证据。每次实验先简述选择理由。
根据已测 TTFT、缓存命中 token 和文本一致性，决定补测、反转顺序复测或结束。
最多做三次 benchmark。把每项结论对应到实际数据和记录路径，
给出复跑命令，说明结论适用的负载和任何仍未验证的问题。
"""


def build_agent(model, run_dir, max_experiments=3, on_event=None):
    def benchmark_prefix_cache(
        workload: Literal["shared", "different"],
        reason: str,
        cache_first: bool = False,
    ) -> dict:
        """Compare cache off and on for one workload. Use shared for long common prefixes,
        different for distinct prefixes, and cache_first to reverse the measurement order.
        Include the hypothesis or observed evidence that motivates this experiment.
        """
        with BENCHMARK_LOCK:
            if on_event:
                on_event({"type": "started", "workload": workload, "reason": reason, "cache_first": cache_first})
            result = run_benchmark(str(CHECKPOINT), cache_first=cache_first, workload=workload)
            artifact = run_dir / f"experiment-{uuid4().hex[:8]}.json"
            command = (
                ".venv/bin/python benchmark/prefix_cache.py models/Qwen3-0.6B-4bit"
                f" --workload {workload}"
            )
            if cache_first:
                command += " --cache-first"
            evidence = {
                "workload": workload,
                "reason": reason,
                "cache_first": cache_first,
                "summary": result["summary"][workload],
                "artifact": str(artifact),
                "reproduce_from_project_root": command,
            }
            artifact.write_text(json.dumps({**evidence, "requests": result["runs"]}, ensure_ascii=False, indent=2))
            if on_event:
                on_event({"type": "completed", **evidence})
            return evidence

    register_harness_profile(
        f"openai:{model.model_name}",
        HarnessProfile(
            excluded_tools=frozenset({"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
    return create_deep_agent(
        model=model,
        tools=[benchmark_prefix_cache],
        system_prompt=INSTRUCTIONS.replace("最多做三次", f"最多做 {max_experiments} 次"),
        middleware=[
            ModelCallLimitMiddleware(run_limit=8),
            ToolCallLimitMiddleware(tool_name="benchmark_prefix_cache", run_limit=max_experiments),
        ],
    )


def run_research(question, run_dir, max_experiments=3, on_event=None):
    load_dotenv(ROOT / ".env")
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise ValueError(f"Fill in DEEPSEEK_API_KEY in {ROOT / '.env'} first.")

    model = ChatOpenAI(
        model=MODEL,
        base_url="https://api.deepseek.com",
        api_key=key,
        use_responses_api=False,
        extra_body={"thinking": {"type": "disabled"}},
        max_tokens=1200,
        timeout=60,
        max_retries=0,
    )
    run_dir.mkdir(parents=True)
    agent = build_agent(model, run_dir, max_experiments, on_event)
    started = time.monotonic()
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    report = result["messages"][-1].text
    usage = {"input_tokens": 0, "output_tokens": 0}
    for message in result["messages"]:
        if isinstance(message, AIMessage) and message.usage_metadata:
            for name in usage:
                usage[name] += message.usage_metadata[name]
    summary = {"question": question, "model": MODEL, "usage": usage, "elapsed_seconds": round(time.monotonic() - started, 2)}
    (run_dir / "report.md").write_text(report + "\n")
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return {"report": report, **summary}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    args = parser.parse_args()
    run_dir = ROOT / "runs" / uuid4().hex[:12]
    try:
        result = run_research(args.question, run_dir)
    except ValueError as error:
        parser.exit(2, f"{error}\n")
    print(result["report"])
    print(f"Run: {run_dir} | {result['usage']}")


if __name__ == "__main__":
    main()
