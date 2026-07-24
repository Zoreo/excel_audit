"""Report store: persisted JSON + HTML reports addressable by a random id.

Local POC storage layout:

    artifacts/reports/{report_id}.html
    artifacts/reports/{report_id}.json

A stored report is reachable at {base_url}/reports/{report_id} once
`excel-auditor serve` is running. Ids are random (secrets.token_hex) which is
adequate for local use only - production deployments need authentication and
real access control (documented limitation).
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings, get_settings

_ID_RE = re.compile(r"^[0-9a-f]{8}$")


@dataclass(frozen=True)
class ReportRef:
    report_id: str
    kind: str
    json_path: Path
    html_path: Path
    url: str


class ReportStore:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._dir = self._settings.reports_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, *, kind: str, report_json: str, report_html: str) -> ReportRef:
        report_id = secrets.token_hex(4)
        json_path = self._dir / f"{report_id}.json"
        html_path = self._dir / f"{report_id}.html"
        json_path.write_text(report_json, encoding="utf-8")
        html_path.write_text(report_html, encoding="utf-8")
        return ReportRef(
            report_id=report_id,
            kind=kind,
            json_path=json_path,
            html_path=html_path,
            url=self.url_for(report_id),
        )

    def url_for(self, report_id: str) -> str:
        return f"{self._settings.base_url}/reports/{report_id}"

    def _path_for(self, report_id: str, suffix: str) -> Path | None:
        # Strict id validation doubles as path-traversal protection.
        if not _ID_RE.match(report_id or ""):
            return None
        path = self._dir / f"{report_id}{suffix}"
        return path if path.is_file() else None

    def load_html(self, report_id: str) -> str | None:
        path = self._path_for(report_id, ".html")
        return path.read_text(encoding="utf-8") if path else None

    def load_json(self, report_id: str) -> str | None:
        path = self._path_for(report_id, ".json")
        return path.read_text(encoding="utf-8") if path else None
