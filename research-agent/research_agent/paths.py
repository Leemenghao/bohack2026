"""Separate bundled, read-only application files from writable research data."""
import os
import shlex
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("LULU_DATA_ROOT", PROJECT_ROOT)).expanduser().resolve()
WEB_ROOT = PROJECT_ROOT / "web"


def replay_command(module, *arguments):
    if "LULU_DATA_ROOT" not in os.environ:
        return shlex.join([".venv/bin/python", "-m", module, *map(str, arguments)])
    return shlex.join(["env", f"LULU_DATA_ROOT={DATA_ROOT}",
                       f"PYTHONPATH={PROJECT_ROOT / 'research-agent'}",
                       sys.executable, "-m", module, *map(str, arguments)])
