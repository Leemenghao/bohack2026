"""Session-owned numeric candidates and evidence-linked lessons."""
import json
from pathlib import Path
from typing import Literal

from research_agent.benchmark.row_normalization import BASELINE, FUNCTIONS, validate_code
from research_agent.runview import RUN_ID, read_json, timestamp


def session_workspace(run_dir):
    current = run_dir
    seen = set()
    while current.name not in seen:
        seen.add(current.name)
        parent = (read_json(current / "run.json") or {}).get("parent_id")
        if not isinstance(parent, str) or not RUN_ID.fullmatch(parent):
            break
        parent_dir = run_dir.parent / parent
        if not parent_dir.is_dir():
            break
        current = parent_dir
    workspace = current / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def make_kernel_tools(record, run_dir, ledger, on_event):
    workspace = session_workspace(run_dir)

    def inspect_kernel_workspace() -> dict:
        """Read the fixed task, baseline, approved numeric API and this session's saved lessons."""
        ledger.check()
        return {
            "workspace": str(workspace), "baseline": BASELINE,
            "contract": "normalize(x): float32 2D array; each row divided by max(L2 norm, 1e-12); input is read-only; output same shape/dtype.",
            "code_rules": "One def normalize(x), no imports. np available. Calls: " + ", ".join(sorted(FUNCTIONS))
                          + ", range, len; x.shape, x.dtype; arithmetic/indexing/for/if. No filesystem, network or package installation.",
            "evaluation": "Submit independent candidates, compare paired median timings. Development and validation use different fixed shapes/seeds, both contain zero/tiny rows.",
            "memory_policy": "记忆是模型基于本机测量的待审核结论。限定输入、dtype、环境；未测因果和带宽不能写成事实。成功、失败、反例均可保存；不以耗时长作为唯一理由。",
            "memory": [json.loads(p.read_text()) for p in sorted(
                workspace.glob("memory-*.json"), key=lambda p: p.stat().st_mtime)[-8:]],
            "latest": read_json(workspace / "latest.json"),
        }

    def benchmark_kernel(code: str, reason: str, suite: Literal["development", "validation"] = "development") -> dict:
        """Save and evaluate a new normalize(x) implementation. Use validation to check the final code on different shapes."""
        try:
            validate_code(code)
        except (ValueError, SyntaxError) as error:
            return {"error": str(error), "correct": False}
        return record({"suite": suite}, reason, {"code": code, "suite": suite}, "")

    def remember_kernel_lesson(lesson: str, conditions: str, why_reusable: str, experiment_ids: list[str]) -> dict:
        """Save a reusable finding or failure lesson to this session, with measured evidence. Decide whether it is worth retaining."""
        ledger.check()
        if not all(isinstance(v, str) and 0 < len(v.strip()) <= 1200 for v in (lesson, conditions, why_reusable)):
            return {"error": "Supply concise lesson, conditions and reuse reason (1–1200 characters)."}
        if not 1 <= len(experiment_ids) <= 6 or any(not isinstance(i, str) or len(i) != 8
                                                   or any(c not in "0123456789abcdef" for c in i) for i in experiment_ids):
            return {"error": "Reference 1–6 current-run experiment IDs."}
        evidence = [read_json(run_dir / f"experiment-{i}.json") for i in experiment_ids]
        if any(not e or e.get("task") != "kernel" or e.get("status") != "completed" for e in evidence):
            return {"error": "Reference completed numeric experiments."}
        from uuid import uuid4
        memory = {"id": uuid4().hex[:8], "scope": "session", "session_id": workspace.parent.name,
                  "run_id": run_dir.name, "lesson": lesson, "conditions": conditions,
                  "why_reusable": why_reusable, "experiment_ids": experiment_ids, "created_at": timestamp(),
                  "origin": "agent", "review_status": "unreviewed"}
        (workspace / f"memory-{memory['id']}.json").write_text(json.dumps(memory, ensure_ascii=False, indent=2))
        (run_dir / f"memory-{memory['id']}.json").write_text(json.dumps(memory, ensure_ascii=False, indent=2))
        identifier = ledger.start("memory", memory_id=memory["id"], estimated_cost_cny=0)
        ledger.finish(identifier, "completed", artifact=f"memory-{memory['id']}.json")
        if on_event:
            on_event({"type": "progress", "stage": "memory", "summary": lesson, "experiment_ids": experiment_ids,
                      "conditions": conditions, "scope": "session"})
        return memory

    return [inspect_kernel_workspace, benchmark_kernel, remember_kernel_lesson]
