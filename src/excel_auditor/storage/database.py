"""SQLite persistence for job metadata.

Trade-off: the plan suggests SQLAlchemy/SQLModel, but the MVP stores a single
flat `jobs` table. The stdlib sqlite3 module keeps the dependency tree small;
swapping in SQLAlchemy later is contained to this package.

Report bodies are NOT stored here: the report store under
`artifacts/reports/` is the single source of truth, so deleting those files
purges a report everywhere. Databases created before this change may still
carry legacy `report_json`/`report_html` blob columns; they are tolerated and
ignored (all reads/writes go through explicit column lists). To purge a legacy
report completely, delete the `artifacts/reports/{report_id}.*` files AND the
legacy blob values in the old DB (e.g. `UPDATE jobs SET report_json = NULL,
report_html = NULL WHERE id = ?` followed by `VACUUM`).
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
    summary_json TEXT
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
