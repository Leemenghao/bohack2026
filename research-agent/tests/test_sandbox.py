import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_agent.research.sandbox import sandbox_command
from research_agent.research.experiments import make_experiment
from research_agent.research.ledger import ResourceLedger

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "darwin", "macOS sandbox integration")
class SandboxTest(unittest.TestCase):
    def test_own_workspace_works_but_other_files_symlinks_and_network_are_denied(self):
        with tempfile.TemporaryDirectory() as temporary, socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen()
            base = Path(temporary)
            run = base / "000000000001"; run.mkdir()
            secret = base / "private.txt"; secret.write_text("not-for-the-agent")
            output = run / "out.json"
            code = f'''import json, os, socket
from pathlib import Path
import numpy as np
checks = {{"numpy": int(np.arange(5).sum()), "clean_environment": os.getenv("DEEPSEEK_API_KEY") is None}}
Path("own.txt").write_text("allowed")
checks["own_read"] = Path("own.txt").read_text()
for name, action in [
    ("outside_read", lambda: Path({str(secret)!r}).read_text()),
    ("outside_write", lambda: Path({str(base / 'outside.txt')!r}).write_text("blocked")),
    ("symlink_read", lambda: Path("link").read_text()),
    ("network", lambda: socket.create_connection(("127.0.0.1", {listener.getsockname()[1]}), 1))]:
    try: action(); checks[name] = False
    except PermissionError: checks[name] = True
print(json.dumps(checks))
'''
            command, cwd, env = sandbox_command([sys.executable, "-c", code], ROOT, run, output)
            (cwd / "link").symlink_to(secret)
            result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            checks = json.loads(result.stdout)
            self.assertEqual(checks.pop("numpy"), 10)
            self.assertEqual(checks.pop("own_read"), "allowed")
            self.assertTrue(all(checks.values()), checks)
            self.assertFalse((base / "outside.txt").exists())

    def test_generated_python_is_recorded_with_isolation_and_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "000000000001"; run.mkdir()
            ledger = ResourceLedger(run)
            execute = make_experiment("python", ROOT, run, ledger=ledger)
            record = execute("print(sum(range(10)))", "Check sandbox execution")
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["summary"]["output"], "45\n")
            self.assertEqual(record["execution"]["isolation"], "macos-seatbelt")
            self.assertGreater(record["resources"]["cpu_seconds"], 0)

    def test_no_unrestricted_fallback(self):
        with patch("research_agent.research.sandbox.sys.platform", "unsupported"):
            with self.assertRaises(RuntimeError):
                sandbox_command([], ROOT, ROOT, ROOT / "unused")
