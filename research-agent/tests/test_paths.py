"""Installed builds must keep writable data separate from application files."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PackagedPathsTest(unittest.TestCase):
    def inspect(self, data_root=None):
        environment = dict(os.environ)
        environment.pop("LULU_DATA_ROOT", None)
        if data_root is not None:
            environment["LULU_DATA_ROOT"] = str(data_root)
        result = subprocess.run([sys.executable, "-c", """
import json
from research_agent.paths import PROJECT_ROOT, DATA_ROOT, WEB_ROOT, replay_command
from research_agent import web_server, cli, settings
print(json.dumps({'project':str(PROJECT_ROOT), 'data':str(DATA_ROOT),
    'web_exists':(WEB_ROOT/'index.html').is_file(),
    'consumer_roots':[str(m.ROOT) for m in (web_server,cli,settings)],
    'replay':replay_command('research_agent.research.sandbox','000000000001','12345678')}))
"""], env=environment, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_installed_data_does_not_redirect_assets_or_require_checkout_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "data with spaces ' and $ characters"
            info = self.inspect(folder)
            self.assertNotEqual(info["project"], info["data"])
            self.assertTrue(info["web_exists"])
            self.assertEqual(info["consumer_roots"], [str(folder.resolve())] * 3)
            command = shlex.split(info["replay"])
            self.assertEqual(command[0], "env")
            self.assertIn(f"LULU_DATA_ROOT={folder.resolve()}", command)
            self.assertIn(sys.executable, command)
            self.assertEqual(command[-2:], ["000000000001", "12345678"])

    def test_development_keeps_existing_data_location(self):
        info = self.inspect()
        self.assertEqual(info["data"], info["project"])
        self.assertTrue(info["web_exists"])
        self.assertEqual(shlex.split(info["replay"])[0], ".venv/bin/python")
