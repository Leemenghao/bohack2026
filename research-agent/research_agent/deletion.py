"""Remove history from active storage, retaining local recovery copies in .trash."""
import json
from contextlib import closing
from uuid import uuid4

from research_agent.runview import read_json, save_run, timestamp


def delete_session(store, session_id):
    turns = store.thread(session_id)
    if not turns:
        raise FileNotFoundError
    trash = store.root / ".trash" / f"session-{session_id}-{uuid4().hex[:8]}"
    trash.mkdir(parents=True)
    moved = []
    try:
        with closing(store.connect()) as db, db:
            for turn in turns:
                folder = store.root / turn["id"]
                if folder.exists():
                    folder.rename(trash / folder.name)
                    moved.append(folder)
            db.execute("DELETE FROM session_summaries WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM turns WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    except Exception:
        for folder in reversed(moved):
            (trash / folder.name).rename(folder)
        raise


def delete_experiment(store, run_id, experiment_id):
    folder = store.root / run_id
    artifact = folder / f"experiment-{experiment_id}.json"
    if not artifact.is_file() or artifact.is_symlink():
        raise FileNotFoundError
    with closing(store.connect()) as db:
        row = db.execute("SELECT session_id FROM turns WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise FileNotFoundError
    trash = folder / ".trash" / f"experiment-{experiment_id}"
    trash.mkdir(parents=True, exist_ok=True)
    for name in (artifact.name, f"candidate-{experiment_id}.py"):
        path = folder / name
        if path.is_file():
            path.rename(trash / name)
    run = read_json(folder / "run.json")
    if run:
        if "events" in run:
            run["events"] = [event for event in run["events"] if event.get("experiment_id") != experiment_id]
        run.setdefault("deleted_experiments", []).append(experiment_id)
        save_run(folder, run)
    # Keep billing totals truthful, but remove the deleted code/result from the active ledger.
    ledger = read_json(folder / "resources.json")
    if ledger:
        for entry in ledger["entries"]:
            if entry.get("experiment_id") == experiment_id:
                for key in ("configuration", "result", "reason", "artifact"):
                    entry.pop(key, None)
                entry["record_deleted"] = True
        (folder / "resources.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
    session_id = row["session_id"]
    # A follow-up may also cite the removed evidence. Withdraw all session digests until regenerated.
    warning = f"> 实验 {run_id}/{experiment_id} 已于 {timestamp()} 删除。历史结论未重新验证，请勿将其当作完整证据。\n\n"
    for turn in store.thread(session_id):
        turn_dir = store.root / turn["id"]
        report = turn_dir / "report.md"
        if report.is_file():
            report.write_text(warning + report.read_text())
        (turn_dir / "session-summary.json").unlink(missing_ok=True)
        for path in list(turn_dir.glob("memory-*.json")) + list((turn_dir / "workspace").glob("memory-*.json")):
            record = read_json(path) or {}
            if record.get("run_id") == run_id and experiment_id in record.get("experiment_ids", []):
                path.unlink()
        latest = turn_dir / "workspace" / "latest.json"
        record = read_json(latest) or {}
        if record.get("run_id") == run_id and record.get("experiment_id") == experiment_id:
            latest.unlink()
    with closing(store.connect()) as db, db:
        db.execute("DELETE FROM session_summaries WHERE session_id=?", (session_id,))
