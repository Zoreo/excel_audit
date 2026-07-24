"""SQLite persistence for job metadata and reports.

Trade-off: the plan suggests SQLAlchemy/SQLModel, but the MVP stores a single
flat `jobs` table. The stdlib sqlite3 module keeps the dependency tree small;
swapping in SQLAlchemy later is contained to this package.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,             -- 'audit' | 'comparison'
    status       TEXT NOT NULL,             -- 'completed' | 'failed'
    error        TEXT,
    created_at   TEXT NOT NULL,
    source_names TEXT,                      -- JSON list of sanitized upload names
    summary_json TEXT,
    report_json  TEXT,
    report_html  TEXT
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path | str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
