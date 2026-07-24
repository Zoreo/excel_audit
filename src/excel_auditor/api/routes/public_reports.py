"""GET /reports/{report_id} - publicly served stored reports (local POC).

Ids are random hex; invalid ids are rejected by the store itself, which is
also the path-traversal guard. Production deployments need authentication.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

router = APIRouter()


@router.get("/reports/{report_id}")
def get_stored_report(
    request: Request,
    report_id: str,
    format: str = Query("html", pattern="^(json|html)$"),
) -> Response:
    store = request.app.state.report_store
    if format == "json":
        payload = store.load_json(report_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Report not found.")
        return Response(content=payload, media_type="application/json")
    html = store.load_html(report_id)
    if html is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return HTMLResponse(content=html)
