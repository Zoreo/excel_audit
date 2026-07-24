"""POST /api/v1/audits - single-workbook risk audit."""

from __future__ import annotations

import logging
import shutil
from uuid import uuid4

from fastapi import APIRouter, Request, UploadFile

from ...reporting.html_report import render_audit_html
from ...reporting.json_report import to_json
from ...services import audit_workbook
from ..schemas import JobResponse
from ..uploads import sanitize_display_name, save_upload

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/v1/audits", response_model=JobResponse, status_code=201)
def create_audit(request: Request, file: UploadFile) -> JobResponse:
    settings = request.app.state.settings
    repo = request.app.state.jobs
    display_name = sanitize_display_name(file.filename)
    scratch = settings.upload_dir / uuid4().hex
    try:
        path = save_upload(file, scratch, settings)
        report = audit_workbook(path, settings=settings, filename=display_name)
        report_json = to_json(report)
        report_html = render_audit_html(report)
        ref = request.app.state.report_store.save(
            kind="audit", report_json=report_json, report_html=report_html
        )
        summary = {
            "risk_level": report.risk_level,
            "risk_drivers": report.risk_drivers,
            "findings": len(report.findings),
            "findings_by_severity": report.findings_by_severity,
            "report_id": ref.report_id,
            "report_url": ref.url,
        }
        job_id = repo.create_completed(
            kind="audit",
            source_names=[display_name],
            summary=summary,
        )
        record = repo.get(job_id)
        return JobResponse(
            id=record.id,
            kind=record.kind,
            status=record.status,
            created_at=record.created_at,
            summary=record.summary,
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
