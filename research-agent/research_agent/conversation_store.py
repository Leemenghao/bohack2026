"""SQLite index for local conversations; reports and evidence live in each run folder."""

import sqlite3
from contextlib import closing

from research_agent.runview import RUN_ID, load_run


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, title TEXT, archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
    parent_id TEXT, question TEXT NOT NULL, task TEXT NOT NULL, created_at TEXT NOT NULL,
    status TEXT NOT NULL, mode TEXT NOT NULL, answer TEXT
);
CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id, created_at);
CREATE INDEX IF NOT EXISTS turns_parent ON turns(parent_id);
CREATE TABLE IF NOT EXISTS session_summaries (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id), source_run_id TEXT NOT NULL,
    content TEXT NOT NULL, updated_at TEXT NOT NULL, model TEXT NOT NULL
);
"""


class ConversationStore:
    def __init__(self, root, *, recover=True):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript(SCHEMA)
            if "shared" not in {row[1] for row in db.execute("PRAGMA table_info(sessions)")}:
                db.execute("ALTER TABLE sessions ADD COLUMN shared INTEGER NOT NULL DEFAULT 0")
        self.import_runs(recover=recover)

    def connect(self):
        db = sqlite3.connect(self.root / "conversations.sqlite3")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @staticmethod
    def _save(db, run_id, run, session_id, answer=None):
        db.execute("INSERT OR IGNORE INTO sessions (id) VALUES (?)", (session_id,))
        db.execute(
            """INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                 answer=COALESCE(excluded.answer, turns.answer)""",
            (run_id, session_id, run.get("parent_id"), run["question"], run["task"],
             run["created_at"], run["status"], run.get("mode", "research"), answer),
        )

    def save(self, run_id, run, answer=None):
        with closing(self.connect()) as db, db:
            parent_id = run.get("parent_id")
            parent = db.execute("SELECT session_id FROM turns WHERE id=?", (parent_id,)).fetchone()
            self._save(db, run_id, run, parent["session_id"] if parent else run_id, answer)

    def import_runs(self, *, recover=False):
        with closing(self.connect()) as db, db:
            known = {row["id"]: dict(row) for row in db.execute("SELECT id, session_id, status FROM turns")}
            candidates = {}
            for folder in self.root.iterdir():
                if not folder.is_dir() or not RUN_ID.fullmatch(folder.name):
                    continue
                row = known.get(folder.name)
                if row and not (recover and row["status"] == "running"):
                    continue
                run = load_run(folder)
                if run:
                    candidates[folder.name] = run

            for run_id, run in candidates.items():
                session_id = run_id
                seen = {run_id}
                parent = run.get("parent_id")
                while parent and parent not in seen:
                    seen.add(parent)
                    if parent in known:
                        session_id = known[parent]["session_id"]
                        break
                    if parent not in candidates:
                        break
                    session_id = parent
                    parent = candidates[parent].get("parent_id")
                if run_id in known:
                    session_id = known[run_id]["session_id"]
                self._save(db, run_id, run, session_id, run.get("answer"))

    def history(self):
        self.import_runs()
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                """SELECT turns.id, turns.session_id, parent_id, question, task, created_at,
                          status, mode, title, archived, shared
                   FROM turns JOIN sessions ON sessions.id = turns.session_id
                   ORDER BY created_at DESC"""
            )]

    def has_follow_up(self, run_id):
        with closing(self.connect()) as db:
            return db.execute("SELECT 1 FROM turns WHERE parent_id=? LIMIT 1", (run_id,)).fetchone() is not None

    def thread(self, session_id):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                """SELECT id, question, created_at, status, mode, answer, parent_id
                   FROM turns WHERE session_id=? ORDER BY created_at, id""",
                (session_id,),
            )]

    def update_session(self, session_id, *, title=None, archived=None, shared=None):
        with closing(self.connect()) as db, db:
            return bool(db.execute(
                """UPDATE sessions SET title=COALESCE(?, title), archived=COALESCE(?, archived), shared=COALESCE(?, shared) WHERE id=?""",
                (title, archived, shared, session_id),
            ).rowcount)

    def save_summary(self, session_id, run_id, content, updated_at, model):
        with closing(self.connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO sessions (id) VALUES (?)", (session_id,))
            db.execute("INSERT OR REPLACE INTO session_summaries VALUES (?, ?, ?, ?, ?)",
                       (session_id, run_id, content, updated_at, model))

    def session_summary(self, session_id):
        with closing(self.connect()) as db:
            row = db.execute("""SELECT s.id, s.shared, s.archived, s.title, m.source_run_id, m.content, m.updated_at, m.model
                FROM sessions s LEFT JOIN session_summaries m ON s.id=m.session_id WHERE s.id=?""", (session_id,)).fetchone()
            return dict(row) if row else None

    def search_summaries(self, query, exclude):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute("""SELECT s.id, s.title, m.content, m.source_run_id, m.updated_at
                FROM sessions s JOIN session_summaries m ON s.id=m.session_id
                WHERE s.shared=1 AND s.archived=0 AND s.id!=? AND (m.content LIKE ? OR s.title LIKE ?)
                ORDER BY m.updated_at DESC LIMIT 5""", (exclude, f"%{query[:200]}%", f"%{query[:200]}%"))]
