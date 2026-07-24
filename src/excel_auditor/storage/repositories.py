"""Job repository. Opens a short-lived connection per operation, which keeps
it safe under FastAPI's threadpool without connection pooling machinery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..errors import JobNotFoundError
from .database import connect, init_db


@dataclass(frozen=True)
class JobRecord:
    id: str
    kind: str
    status: str
    error: str | None
    created_at: str
    source_names: list[str]
    summary: dict[str, Any] | None


class JobRepository:
    def __init__(self, db_path: Path | str):
        self._db_path = Path(db_path)
        init_db(self._db_path)

    def create_completed(
        self,
        *,
        kind: str,
        source_names: list[str],
        summary: dict[str, Any],
    ) -> str:
        job_id = uuid4().hex
        with connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO jobs (id, kind, status, created_at, source_names,"
                " summary_json)"
                " VALUES (?, ?, 'completed', ?, ?, ?)",
                (
                    job_id,
                    kind,
                    datetime.now(UTC).isoformat(),
                    json.dumps(source_names),
                    json.dumps(summary),
                ),
            )
        return job_id

    def create_failed(self, *, kind: str, source_names: list[str], error: str) -> str:
        job_id = uuid4().hex
        with connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO jobs (id, kind, status, error, created_at, source_names)"
                " VALUES (?, ?, 'failed', ?, ?, ?)",
                (job_id, kind, error, datetime.now(UTC).isoformat(), json.dumps(source_names)),
            )
        return job_id

    def get(self, job_id: str) -> JobRecord:
        # Explicit column list: legacy databases may still carry the retired
        # report_json/report_html blob columns, which are ignored on purpose.
        with connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT id, kind, status, error, created_at, source_names,"
                " summary_json FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise JobNotFoundError(f"No job with id {job_id!r}.")
        return JobRecord(
            id=row["id"],
            kind=row["kind"],
            status=row["status"],
            error=row["error"],
            created_at=row["created_at"],
            source_names=json.loads(row["source_names"] or "[]"),
            summary=json.loads(row["summary_json"]) if row["summary_json"] else None,
        )
