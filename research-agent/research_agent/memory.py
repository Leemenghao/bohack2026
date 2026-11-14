"""Carry the previous run's conclusion into the next one.

The track asks for research results that can "sustainably improve". Without
memory every run starts from zero and may repeat an experiment that was already
done. This module finds the most recent finished run and turns its report into a
short prompt block.

Pure filesystem logic: no model, no network, so it is testable offline.
"""

import re
import json
from pathlib import Path

MAX_MEMORY_CHARS = 700


def list_runs(runs_root: Path) -> list[Path]:
    """Directories that contain a finished report, newest first."""
    if not runs_root.is_dir():
        return []
    runs = [
        path
        for path in runs_root.iterdir()
        if path.is_dir() and (path / "report.md").is_file()
    ]
    return sorted(runs, key=lambda path: (path / "report.md").stat().st_mtime, reverse=True)


def load_previous(runs_root: Path, exclude: Path | None = None) -> dict | None:
    """Return {run_id, text} for the newest run other than `exclude`."""
    exclude = exclude.resolve() if exclude else None
    for run_dir in list_runs(runs_root):
        if exclude and run_dir.resolve() == exclude:
            continue
        summary_path = run_dir / "summary.json"
        if summary_path.is_file():
            try:
                if json.loads(summary_path.read_text()).get("status", "complete") != "complete":
                    continue
            except (ValueError, AttributeError):
                continue
        text = (run_dir / "report.md").read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return {"run_id": run_dir.name, "text": text}
    return None


def condense(text: str, limit: int = MAX_MEMORY_CHARS) -> str:
    """Keep the head of the report, which holds the conclusion, and mark truncation."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Prefer to stop at a paragraph boundary.
    boundary = cut.rfind("\n\n")
    if boundary > limit * 0.6:
        cut = cut[:boundary]
    return cut.rstrip() + "\n…（已截断）"


def memory_block(previous: dict | None) -> str:
    """Prompt section describing the previous run, or an empty string."""
    if not previous:
        return ""
    body = condense(re.sub(r"\n{3,}", "\n\n", previous["text"]))
    return (
        "【上一次研究的结论】\n"
        f"来自运行 {previous['run_id']}，仅供参照：它是上一轮条件下的观察，不能当作本轮实测结果。\n"
        f"{body}\n"
        "本轮如果重复同一实验，请说明为什么需要重测；如果能沿用上一次的结论，请直接引用并说明依据。"
    )
