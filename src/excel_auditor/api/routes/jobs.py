"""GET /api/v1/jobs/{job_id} and GET /api/v1/reports/{job_id}."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from ...errors import JobNotFoundError
from ..schemas import JobResponse

router = APIRouter()


@router.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
def get_job(request: Request, job_id: str) -> JobResponse:
    try:
        record = request.app.state.jobs.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JobResponse(
        id=record.id,
        kind=record.kind,
        status=record.status,
        created_at=record.created_at,
        error=record.error,
        summary=record.summary,
    )


@router.get("/api/v1/reports/{job_id}")
def get_report(
    request: Request,
    job_id: str,
    format: str = Query("json", pattern="^(json|html)$"),
) -> Response:
    try:
        record = request.app.state.jobs.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if record.status != "completed":
        raise HTTPException(status_code=409, detail=f"Job status is '{record.status}'.")
    # Report bodies live only in the report store; deleting the stored files
    # purges the report from this endpoint and /reports/{report_id} alike.
    report_id = (record.summary or {}).get("report_id") or ""
    store = request.app.state.report_store
    if format == "html":
        html = store.load_html(report_id)
        if html is None:
            raise HTTPException(status_code=404, detail="No HTML report stored.")
        return HTMLResponse(content=html)
    payload = store.load_json(report_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No JSON report stored.")
    return Response(content=payload, media_type="application/json")
