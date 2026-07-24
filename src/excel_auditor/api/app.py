"""FastAPI application factory.

Processing is synchronous for the MVP (small files); the job store already
records results by job id, so moving to background workers later only changes
the route handlers, not the storage or clients.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .. import __version__
from ..config import Settings, get_settings
from ..errors import WorkbookLoadError, WorkbookValidationError
from ..storage.reports import ReportStore
from ..storage.repositories import JobRepository
from ..web import routes as web_routes
from .routes import audits, comparisons, jobs, public_reports, queries, workbook_schema
from .schemas import HealthResponse

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()

    app = FastAPI(
        title="Excel Auditor",
        version=__version__,
        description="Deterministic audit and comparison engine for Excel workbooks.",
    )
    app.state.settings = settings
    app.state.jobs = JobRepository(settings.db_path)
    app.state.report_store = ReportStore(settings)

    app.include_router(audits.router)
    app.include_router(comparisons.router)
    app.include_router(jobs.router)
    app.include_router(public_reports.router)
    app.include_router(workbook_schema.router)
    app.include_router(queries.router)
    app.include_router(web_routes.router)

    @app.exception_handler(WorkbookValidationError)
    def _validation_error(request: Request, exc: WorkbookValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(WorkbookLoadError)
    def _load_error(request: Request, exc: WorkbookLoadError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app


# No module-level app instance: creating one at import time would touch the
# filesystem (data/artifacts dirs). Run via the factory instead:
#   uvicorn --factory excel_auditor.api.app:create_app
