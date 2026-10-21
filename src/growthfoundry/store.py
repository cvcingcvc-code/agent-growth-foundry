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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)

    def put(self, item: dict, state: str, reason: str):
        if state not in ALLOWED_STATES:
            raise ValueError("invalid state")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO candidates(id,title,license,source_url,state,reason,created_at) VALUES(?,?,?,?,?,?,?)",
                            (item["id"], item["title"], item["license"], item["source_url"], state, reason, now()))
            self.db.execute("INSERT INTO events(candidate_id,state,note,time_utc) VALUES(?,?,?,?)", (item["id"], state, reason, now()))

    def list_items(self):
        return [dict(zip([d[0] for d in cursor.description], row)) for cursor in [self.db.execute("SELECT id,title,license,source_url,state,reason FROM candidates ORDER BY id")] for row in cursor.fetchall()]

    def close(self):
        self.db.close()
