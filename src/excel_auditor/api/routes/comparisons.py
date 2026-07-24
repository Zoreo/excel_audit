"""POST /api/v1/comparisons - compare two workbook versions."""

from __future__ import annotations

import logging
import shutil
from uuid import uuid4

from fastapi import APIRouter, Request, UploadFile

from ...reporting.html_report import render_comparison_html
from ...reporting.json_report import to_json
from ...services import compare_workbooks
from ..schemas import JobResponse
from ..uploads import sanitize_display_name, save_upload

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/v1/comparisons", response_model=JobResponse, status_code=201)
def create_comparison(request: Request, old_file: UploadFile, new_file: UploadFile) -> JobResponse:
    settings = request.app.state.settings
    repo = request.app.state.jobs
    old_name = sanitize_display_name(old_file.filename)
    new_name = sanitize_display_name(new_file.filename)
    scratch = settings.upload_dir / uuid4().hex
    try:
        old_path = save_upload(old_file, scratch, settings)
        new_path = save_upload(new_file, scratch, settings)
        report = compare_workbooks(
            old_path,
            new_path,
            settings=settings,
            old_filename=old_name,
            new_filename=new_name,
        )
        report_json = to_json(report)
        report_html = render_comparison_html(report)
        ref = request.app.state.report_store.save(
            kind="comparison", report_json=report_json, report_html=report_html
        )
        summary = {
            "risk_level": report.risk_level,
            "risk_drivers": report.risk_drivers,
            "review_items": report.summary.total_review_items,
            "total_cell_changes": report.summary.total_cell_changes,
            "structural_changes": report.summary.structural_change_count,
            "high_impact_changes": report.summary.high_impact_changes,
            "findings": len(report.findings),
            "report_id": ref.report_id,
            "report_url": ref.url,
        }
        job_id = repo.create_completed(
            kind="comparison",
            source_names=[old_name, new_name],
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
