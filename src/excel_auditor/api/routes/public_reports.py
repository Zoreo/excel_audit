"""GET /reports/{report_id} - publicly served stored reports (local POC).

Ids are random hex; invalid ids are rejected by the store itself, which is
also the path-traversal guard. Production deployments need authentication.

``format=pdf`` serves the stored ``{id}.pdf`` when present; otherwise the
PDF is rendered on demand from the stored HTML (side-effect free: nothing is
persisted by a GET). A missing report is a 404; a present report on a host
without the optional ``[pdf]`` extra is a 422 with the install hint.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from ...errors import PdfExportUnavailableError
from ...reporting.pdf_report import render_pdf

router = APIRouter()


@router.get("/reports/{report_id}")
def get_stored_report(
    request: Request,
    report_id: str,
    format: str = Query("html", pattern="^(json|html|pdf)$"),
) -> Response:
    store = request.app.state.report_store
    if format == "json":
        payload = store.load_json(report_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Report not found.")
        return Response(content=payload, media_type="application/json")
    if format == "pdf":
        pdf = store.load_pdf(report_id)
        if pdf is None:
            html = store.load_html(report_id)
            if html is None:
                raise HTTPException(status_code=404, detail="Report not found.")
            try:
                pdf = render_pdf(html)
            except PdfExportUnavailableError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(content=pdf, media_type="application/pdf")
    html = store.load_html(report_id)
    if html is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return HTMLResponse(content=html)
