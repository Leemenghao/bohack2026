"""macOS Seatbelt boundary for model-authored Python and numeric candidates."""
import json
import sys
from pathlib import Path
from uuid import uuid4

from research_agent.research.kernel import session_workspace
from research_agent.paths import DATA_ROOT, PROJECT_ROOT


def sandbox_command(command, root, run_dir, output):
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError("Sandbox unavailable; generated code was not executed.")
    workspace = session_workspace(run_dir).resolve()
    temporary = workspace / "tmp"
    temporary.mkdir(exist_ok=True)
    read_roots = ["/System", "/usr", "/bin", "/sbin", "/Library/Developer", "/Library/Apple",
                  str(Path(sys.base_prefix).resolve()), str((root / ".venv").resolve()),
                  str((PROJECT_ROOT / "research-agent").resolve()), str(run_dir.resolve()), str(workspace)]
    quote = lambda path: json.dumps(str(path), ensure_ascii=False)
    profile = "\n".join([
        "(version 1)", "(deny default)", "(allow process-exec process-fork)",
        "(allow file-read-metadata)", "(allow sysctl-read)", "(allow signal (target self))",
        '(allow mach-lookup (global-name "com.apple.system.logger"))',
        "(allow file-read* file-map-executable " + " ".join(f"(subpath {quote(path)})" for path in read_roots) + ")",
        '(allow file-read* (literal "/"))',
        '(allow file-read* (subpath "/dev") (literal "/private/etc/localtime"))',
        '(allow file-write* (literal "/dev/null"))',
        f"(allow file-write* (subpath {quote(workspace)}) (literal {quote(output.resolve())}))",
    ])
    profile_path = run_dir / f"sandbox-{uuid4().hex[:8]}.sb"
    profile_path.write_text(profile)
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(workspace), "TMPDIR": str(temporary),
                   "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                   "PYTHONPATH": str(PROJECT_ROOT / "research-agent")}
    return ["/usr/bin/sandbox-exec", "-f", str(profile_path), *command], workspace, environment


if __name__ == "__main__":
    import argparse
    from threading import Event
    from research_agent.research.experiments import run_worker
    from research_agent.runview import RUN_ID
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("experiment_id")
    args = parser.parse_args()
    if not RUN_ID.fullmatch(args.run_id) or len(args.experiment_id) != 8 or any(c not in "0123456789abcdef" for c in args.experiment_id):
        parser.error("Invalid record ID")
    root = DATA_ROOT
    folder = root / "runs" / args.run_id
    record = json.loads((folder / f"experiment-{args.experiment_id}.json").read_text())
    task = record["task"]
    source = folder / f"candidate-{args.experiment_id}.py"
    if task not in ("kernel", "python") or source.is_symlink():
        parser.error("Not a sandbox experiment")
    configuration = {"source": str(source)} if task == "python" else {"code": source.read_text(), "suite": record["suite"]}
    output = folder / f"replay-{uuid4().hex[:8]}.json"
    command, cwd, environment = sandbox_command([sys.executable, "-m", "research_agent.research.worker", task,
        str(output), json.dumps(configuration)], root, folder, output)
    run_worker(command, cwd, Event(), 30, env=environment)
    print(output.read_text())
