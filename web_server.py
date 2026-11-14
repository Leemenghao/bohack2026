"""Launch the workbench from a checkout, including when model deps are absent."""

from pathlib import Path
from runpy import run_path


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    run_path(str(root / "research-agent/research_agent/web_server.py"), run_name="__main__")
