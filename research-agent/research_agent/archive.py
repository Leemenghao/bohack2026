"""Package one run's artefacts into a zip.

Judges and teammates need to take the evidence with them: the report alone is not
enough, the request-level records are what make the numbers checkable. This module
is pure filesystem + stdlib zip, so it is testable without a model.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

INCLUDE = ("report.md", "summary.json", "run.json", "resources.json", "session-summary.json")
PATTERNS = ("experiment-*.json", "search-*.json", "source-*.json", "candidate-*.py", "memory-*.json", "delegation-*.json")


def run_files(run_dir: Path) -> list[Path]:
    """Artefacts of one run, report first."""
    if not run_dir.is_dir():
        return []
    files = [run_dir / name for name in INCLUDE if (run_dir / name).is_file()]
    for pattern in PATTERNS:
        files.extend(sorted(run_dir.glob(pattern)))
    return files


def build_archive(run_dir: Path, run_id: str | None = None) -> bytes:
    """Return a zip containing the run's artefacts. Raises FileNotFoundError if empty."""
    files = run_files(run_dir)
    if not files:
        raise FileNotFoundError(run_dir)
    prefix = run_id or run_dir.name
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=f"{prefix}/{path.name}")
    return buffer.getvalue()
