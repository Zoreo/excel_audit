"""POST /api/v1/schema - detect tables, headers and column types."""

from __future__ import annotations

import shutil
from uuid import uuid4

from fastapi import APIRouter, Request, UploadFile

from ...query_service import inspect_schema
from ...reporting.html_report import render_schema_html
from ...reporting.json_report import to_json
from ..uploads import sanitize_display_name, save_upload

router = APIRouter()


@router.post("/api/v1/schema", status_code=201)
def create_schema(request: Request, file: UploadFile) -> dict:
    settings = request.app.state.settings
    display_name = sanitize_display_name(file.filename)
    scratch = settings.upload_dir / uuid4().hex
    try:
        path = save_upload(file, scratch, settings)
        report = inspect_schema(path, settings=settings, filename=display_name)
        ref = request.app.state.report_store.save(
            kind="schema",
            report_json=to_json(report),
            report_html=render_schema_html(report),
        )
        schema = report.workbook_schema
        return {
            "status": "completed",
            "report_id": ref.report_id,
            "report_url": ref.url,
            "sheets": [s.name for s in schema.sheets],
            "tables": [
                {
                    "sheet": t.sheet_name,
                    "ref": t.ref,
                    "rows": t.row_count,
                    "columns": [
                        {"name": c.name, "type": c.type.value, "currency": c.currency}
                        for c in t.columns
                    ],
                }
                for t in schema.tables
            ],
            "warnings": schema.warnings,
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
