"""Report store: persisted JSON + HTML reports addressable by a random id.

Local POC storage layout:

    artifacts/reports/{report_id}.html
    artifacts/reports/{report_id}.json
    artifacts/reports/{report_id}.pdf   (optional, only when PDF export was requested)

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

# New ids are 128-bit (32 hex chars); 8-hex ids predate the widening and must
# stay loadable so previously stored reports do not 404.
_ID_RE = re.compile(r"^(?:[0-9a-f]{8}|[0-9a-f]{32})$")

_MAX_ID_ATTEMPTS = 16


@dataclass(frozen=True)
class ReportRef:
    report_id: str
    kind: str
    json_path: Path
    html_path: Path
    url: str
    # Present only when a PDF copy was stored alongside the JSON/HTML pair.
    pdf_path: Path | None = None


class ReportStore:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._dir = self._settings.reports_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        kind: str,
        report_json: str,
        report_html: str,
        report_pdf: bytes | None = None,
    ) -> ReportRef:
        # Exclusive create ("x") so an id collision can never silently
        # overwrite an existing report; on collision pick a fresh id.
        for _ in range(_MAX_ID_ATTEMPTS):
            report_id = secrets.token_hex(16)
            json_path = self._dir / f"{report_id}.json"
            html_path = self._dir / f"{report_id}.html"
            pdf_path = self._dir / f"{report_id}.pdf"
            try:
                with open(json_path, "x", encoding="utf-8") as fh:
                    fh.write(report_json)
            except FileExistsError:
                continue
            try:
                with open(html_path, "x", encoding="utf-8") as fh:
                    fh.write(report_html)
            except FileExistsError:
                json_path.unlink(missing_ok=True)
                continue
            if report_pdf is not None:
                try:
                    with open(pdf_path, "xb") as bfh:
                        bfh.write(report_pdf)
                except FileExistsError:
                    json_path.unlink(missing_ok=True)
                    html_path.unlink(missing_ok=True)
                    continue
            return ReportRef(
                report_id=report_id,
                kind=kind,
                json_path=json_path,
                html_path=html_path,
                url=self.url_for(report_id),
                pdf_path=pdf_path if report_pdf is not None else None,
            )
        raise RuntimeError("Could not allocate a unique report id.")

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

    def load_pdf(self, report_id: str) -> bytes | None:
        path = self._path_for(report_id, ".pdf")
        return path.read_bytes() if path else None
