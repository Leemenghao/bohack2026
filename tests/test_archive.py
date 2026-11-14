"""Tests for the run archive. Filesystem + stdlib only."""

import io
import shutil
import unittest
import uuid
import zipfile
from pathlib import Path

from archive import build_archive, run_files

RUNS_ROOT = Path(__file__).resolve().parent / ".runs"


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.run = RUNS_ROOT / uuid.uuid4().hex[:8]
        self.run.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.run, ignore_errors=True)

    def touch(self, name, text="{}"):
        (self.run / name).write_text(text, encoding="utf-8")

    def test_empty_run_has_no_files(self):
        self.assertEqual(run_files(self.run), [])
        with self.assertRaises(FileNotFoundError):
            build_archive(self.run)

    def test_report_comes_first(self):
        self.touch("experiment-aaaaaaaa.json")
        self.touch("report.md", "# 报告")
        self.touch("summary.json", "{}")
        names = [path.name for path in run_files(self.run)]
        self.assertEqual(names[0], "report.md")
        self.assertIn("experiment-aaaaaaaa.json", names)

    def test_archive_is_valid_zip_with_prefixed_entries(self):
        self.touch("report.md", "# 报告")
        self.touch("experiment-aaaaaaaa.json")
        self.touch("search-bbbbbbbb.json")
        self.touch("source-cccccccc.json")
        self.touch("notes.txt")  # not part of the archive

        data = build_archive(self.run, run_id="run123")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = sorted(archive.namelist())

        self.assertEqual(
            names,
            [
                "run123/experiment-aaaaaaaa.json",
                "run123/report.md",
                "run123/search-bbbbbbbb.json",
                "run123/source-cccccccc.json",
            ],
        )
        self.assertNotIn("run123/notes.txt", names)

    def test_archive_roundtrips_text(self):
        self.touch("report.md", "结论：降幅 84.6%")
        data = build_archive(self.run)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            name = archive.namelist()[0]
            self.assertEqual(archive.read(name).decode("utf-8"), "结论：降幅 84.6%")

    def test_falls_back_to_directory_name(self):
        self.touch("report.md", "# 报告")
        data = build_archive(self.run)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertTrue(archive.namelist()[0].startswith(f"{self.run.name}/"))


if __name__ == "__main__":
    unittest.main()
