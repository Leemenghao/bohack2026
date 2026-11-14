"""Store local run state alongside its report and experiment records."""

import json
import re
from datetime import datetime, timezone


RUN_ID = re.compile(r"[a-f0-9]{12}")
HISTORY_FIELDS = ("question", "task", "created_at", "status")


def continuation_context(runs_root, parent_id):
    """Read the selected thread only, keeping model context bounded."""
    from memory import condense

    turns = []
    seen = set()
    while parent_id and RUN_ID.fullmatch(parent_id) and parent_id not in seen:
        seen.add(parent_id)
        folder = runs_root / parent_id
        run = load_run(folder)
        if not run:
            break
        turns.append((parent_id, folder, run))
        parent_id = run.get("parent_id")
    if not turns:
        return ""
    sections = ["原始研究问题：" + turns[-1][2]["question"]]
    for run_id, folder, run in reversed(turns[:3]):
        experiments = []
        for path in sorted(folder.glob("experiment-*.json")):
            record = read_json(path)
            if record and record.get("summary"):
                keys = ("experiment_id", "split_seed", "workload", "cache_first", "summary")
                experiments.append({key: record[key] for key in keys if key in record})
        report = folder / "report.md"
        sections.append(
            f"历史轮次 {run_id}（{run['status']}）\n用户：{run['question']}\n"
            + (condense(report.read_text(), 1000) if report.is_file() else "此轮未生成报告。")
            + "\n历史实测：" + json.dumps(experiments[-4:], ensure_ascii=False)
        )
    return "\n\n".join(sections)


def timestamp(epoch=None):
    if epoch is None:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def read_json(path):
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def save_run(folder, run):
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / "run.json.tmp"
    temporary.write_text(json.dumps(run, ensure_ascii=False))
    temporary.replace(folder / "run.json")


def load_run(folder, *, include_detail=False):
    run = read_json(folder / "run.json")
    summary = read_json(folder / "summary.json")
    report = folder / "report.md"
    has_report = report.is_file()
    summary = summary or {}
    if run is None:
        if not has_report:
            return None
        run = {
            "question": summary.get("question", ""),
            "task": summary.get("task", "prefix_cache"),
            "created_at": timestamp(report.stat().st_mtime),
            "status": summary.get("status", "complete"),
        }
    elif run["status"] == "running":
        if has_report:
            run["status"] = summary.get("status", "complete")
        else:
            run.update(status="interrupted", error="上次运行已中断，可以查看已保存的过程。")
    if summary.get("answer"):
        run["answer"] = summary["answer"]
    if summary.get("mode"):
        run.setdefault("mode", summary["mode"])

    if include_detail:
        ledger = read_json(folder / "resources.json")
        if ledger:
            run["resources"] = ledger["summary"]
        if has_report:
            run["result"] = {
                "question": "", "elapsed_seconds": 0, "usage": {"input_tokens": 0, "output_tokens": 0},
                **summary, "report": report.read_text(),
            }
        if "events" not in run:
            run["events"] = build_events(folder)
    return run


def build_events(folder):
    events = []
    summary = read_json(folder / "summary.json") or {}
    if summary.get("budget"):
        events.append({"type": "budget", **summary["budget"]})
    if summary.get("memory_from"):
        events.append({"type": "memory", "run_id": summary["memory_from"]})
    decisions = summary.get("experiment_decisions", [])
    files = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for path in files:
        if path.name.startswith(("search-", "source-", "experiment-")):
            data = read_json(path)
            if data is None:
                continue
            if path.name.startswith("search-"):
                events.extend({"type": "source", "query": data.get("query", ""), **source} for source in data.get("sources", []))
            elif path.name.startswith("source-"):
                data.pop("content", None)
                events.append({"type": "source_fetched", **data})
            elif path.name.startswith("experiment-"):
                data.pop("requests", None)
                data.setdefault("artifact", path.name)
                end = "completed" if data.get("status", "completed") == "completed" else "experiment_failed"
                events.extend({"type": kind, **data} for kind in ("started", end))
                events.extend(decision for decision in decisions
                              if data.get("experiment_id") in decision["experiment_ids"])
    return events
