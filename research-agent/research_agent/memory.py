"""Carry an explicitly shared session digest into a CLI run.

The track asks for research results that can "sustainably improve". Without
memory every run starts from zero and may repeat an experiment that was already
done. This module reads user-shared summaries and formats a short prompt block.

Pure filesystem logic: no model, no network, so it is testable offline.
"""

import re
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
    """Return the newest explicitly shared, non-archived session digest."""
    if not (runs_root / "conversations.sqlite3").is_file():
        return None
    from research_agent.conversation_store import ConversationStore
    store = ConversationStore(runs_root, recover=False)
    for summary in store.search_summaries("", exclude.name if exclude else ""):
        if exclude and summary["source_run_id"] == exclude.name:
            continue
        return {"run_id": summary["source_run_id"], "text": summary["content"]}
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
        "【共享研究摘要】\n"
        f"来自运行 {previous['run_id']}，仅供参照：它是上一轮条件下的观察，不能当作本轮实测结果。\n"
        f"{body}\n"
        "本轮如果重复同一实验，请说明为什么需要重测；如果能沿用上一次的结论，请直接引用并说明依据。"
    )
