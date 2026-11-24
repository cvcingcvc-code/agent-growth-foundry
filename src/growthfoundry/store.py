"""Durable single-writer SQLite job intake and stage transitions."""
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
 id TEXT PRIMARY KEY,
 title TEXT NOT NULL,
 license TEXT NOT NULL,
 source_url TEXT NOT NULL,
 state TEXT NOT NULL,
 reason TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 candidate_id TEXT NOT NULL,
 state TEXT NOT NULL,
 note TEXT NOT NULL,
 time_utc TEXT NOT NULL
);
"""
ALLOWED_STATES = {"DISCOVERED", "REVIEW", "BLOCKED", "BUILDING", "TESTING", "READY_FOR_REVIEW", "FAILED", "ARCHIVED"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30.0)
        try:
            if str(self.path) != ":memory:":
                self.db.execute("PRAGMA journal_mode=WAL;")
                self.db.execute("PRAGMA synchronous=NORMAL;")
        except sqlite3.OperationalError:
            pass
        self.db.executescript(SCHEMA)

    def put(self, item: dict, state: str, reason: str):
        if state not in ALLOWED_STATES:
            raise ValueError("invalid state")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO candidates(id,title,license,source_url,state,reason,created_at) VALUES(?,?,?,?,?,?,?)",
                            (item["id"], item["title"], item["license"], item["source_url"], state, reason, now()))
            self.db.execute("INSERT INTO events(candidate_id,state,note,time_utc) VALUES(?,?,?,?)", (item["id"], state, reason, now()))

    def advance_state(self, candidate_id: str, new_state: str, reason: str = "", note: str = ""):
        if new_state not in ALLOWED_STATES:
            raise ValueError(f"invalid state: {new_state}")
        event_note = note if note else reason
        with self.db:
            cursor = self.db.execute("UPDATE candidates SET state=?, reason=? WHERE id=?",
                                     (new_state, reason, candidate_id))
            if cursor.rowcount == 0:
                raise KeyError(f"candidate not found: {candidate_id}")
            self.db.execute("INSERT INTO events(candidate_id,state,note,time_utc) VALUES(?,?,?,?)",
                            (candidate_id, new_state, event_note, now()))

    def list_items(self):
        return [dict(zip([d[0] for d in cursor.description], row)) for cursor in [self.db.execute("SELECT id,title,license,source_url,state,reason FROM candidates ORDER BY id")] for row in cursor.fetchall()]

    def close(self):
        self.db.close()
