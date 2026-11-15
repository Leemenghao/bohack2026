"""Launch the workbench from a source checkout."""

import sys
from pathlib import Path
from runpy import run_module


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "research-agent"))
    run_module("research_agent.web_server", run_name="__main__")
