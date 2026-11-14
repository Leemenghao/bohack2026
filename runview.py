"""Read a finished run from disk back into the shape the UI expects.

`web_server` keeps in-memory state only for the current process, so after a
restart (or on a machine without the model stack) the recorded runs under
`runs/` would look lost. These helpers rebuild a view from the files so the
workbench can still show real, previously recorded evidence.

Pure filesystem logic, testable offline.
"""

import json
from pathlib import Path


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def list_recorded_runs(runs_root: Path) -> list[dict]:
    """Finished runs under `runs/`, newest first, with a short label."""
    if not runs_root.is_dir():
        return []
    rows = []
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir():
            continue
        report = run_dir / "report.md"
        summary = run_dir / "summary.json"
        if not report.is_file():
            continue
        data = _read_json(summary)
        rows.append({
            "id": run_dir.name,
            "question": (data.get("question") or "").strip(),
            "elapsed_seconds": data.get("elapsed_seconds"),
            "memory_from": data.get("memory_from"),
            "recorded_at": report.stat().st_mtime,
        })
    rows.sort(key=lambda row: row["recorded_at"], reverse=True)
    return rows


def build_events(run_dir: Path) -> list[dict]:
    """Rebuild the event stream from the artefacts on disk."""
    events: list[dict] = []
    summary = _read_json(run_dir / "summary.json")
    if summary.get("budget"):
        events.append({"type": "budget", **summary["budget"]})
    if summary.get("memory_from"):
        events.append({"type": "memory", "run_id": summary["memory_from"]})

    for path in sorted(run_dir.glob("search-*.json")):
        payload = _read_json(path)
        for item in payload.get("sources", []):
            events.append({
                "type": "source",
                "query": payload.get("query", ""),
                "source_id": item.get("source_id", ""),
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "excerpt": item.get("excerpt", ""),
            })

    for path in sorted(run_dir.glob("source-*.json")):
        payload = _read_json(path)
        events.append({
            "type": "source_fetched",
            "source_id": payload.get("source_id", ""),
            "title": payload.get("title", ""),
            "url": payload.get("url", ""),
            "content_kind": payload.get("content_kind", ""),
            "artifact": payload.get("artifact", ""),
        })

    for path in sorted(run_dir.glob("experiment-*.json")):
        payload = _read_json(path)
        common = {
            "workload": payload.get("workload"),
            "reason": payload.get("reason", ""),
            "cache_first": payload.get("cache_first", False),
        }
        events.append({"type": "started", **common})
        events.append({
            "type": "completed",
            **common,
            "summary": payload.get("summary"),
            "artifact": payload.get("artifact", ""),
            "reproduce_from_project_root": payload.get("reproduce_from_project_root", ""),
        })
    return events


def load_run_view(run_dir: Path) -> dict | None:
    """A completed run payload for the API, or None when the run has no report."""
    report = run_dir / "report.md"
    if not report.is_file():
        return None
    summary = _read_json(run_dir / "summary.json")
    return {
        "status": "complete",
        "events": build_events(run_dir),
        "result": {
            "report": report.read_text(encoding="utf-8"),
            "question": summary.get("question", ""),
            "model": summary.get("model", ""),
            "usage": summary.get("usage", {"input_tokens": 0, "output_tokens": 0}),
            "elapsed_seconds": summary.get("elapsed_seconds", 0),
            "budget": summary.get("budget"),
            "memory_from": summary.get("memory_from"),
        },
    }
