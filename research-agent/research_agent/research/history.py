"""Store local run state alongside its report and experiment records."""

import json
import re
from datetime import datetime, timezone


RUN_ID = re.compile(r"[a-f0-9]{12}")
HISTORY_FIELDS = ("question", "task", "created_at", "status")


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
    has_report = summary is not None and (folder / "report.md").is_file()
    if run is None:
        if not has_report or not summary.get("question"):
            return None
        run = {
            "question": summary["question"],
            "task": summary.get("task", "prefix_cache"),
            "created_at": timestamp((folder / "summary.json").stat().st_mtime),
            "status": "complete",
        }
    elif run["status"] == "running":
        if has_report:
            run["status"] = "complete"
        else:
            run.update(status="interrupted", error="上次运行已中断，可以查看已保存的过程。")

    if include_detail:
        if has_report and run["status"] == "complete":
            run["result"] = {**summary, "report": (folder / "report.md").read_text()}
        if "events" not in run:
            run["events"] = legacy_events(folder)
    return run


def legacy_events(folder):
    events = []
    files = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for path in files:
        if path.name.startswith(("search-", "source-", "experiment-")):
            data = read_json(path)
            if data is None:
                continue
            if path.name.startswith("search-"):
                events.extend({"type": "source", **source} for source in data.get("sources", []))
            elif path.name.startswith("source-"):
                data.pop("content", None)
                events.append({"type": "source_fetched", **data})
            else:
                data.pop("requests", None)
                events.extend({"type": kind, **data} for kind in ("started", "completed"))
    return events
