"""Minimal server-rendered pages: audit / compare / ask / open a report.

Demonstration-only. Forms call the same application services as the CLI and
API - no business logic lives here. For the ask flow, the uploaded file is
parked under artifacts/uploads with a random token so the confirmation step
can re-run the query without re-uploading; the file is deleted as soon as the
question is answered.
"""

from __future__ import annotations

import secrets
import shutil

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, PackageLoader, select_autoescape

from ..api.uploads import sanitize_display_name, save_upload
from ..llm import UnsupportedQuestionError, get_parser
from ..models.query import ResultStatus
from ..query_service import answer_query, inspect_schema
from ..reporting.html_report import (
    render_audit_html,
    render_comparison_html,
    render_query_html,
)
from ..reporting.json_report import to_json
from ..services import audit_workbook, compare_workbooks

router = APIRouter(include_in_schema=False)

_env = Environment(
    loader=PackageLoader("excel_auditor.web", "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
)


def _page(name: str, **context) -> HTMLResponse:
    return HTMLResponse(_env.get_template(name).render(**context))


@router.get("/")
def index() -> HTMLResponse:
    return _page("index.html.j2")


@router.get("/audit")
def audit_form() -> HTMLResponse:
    return _page("audit.html.j2")


@router.post("/audit")
def audit_submit(request: Request, file: UploadFile) -> RedirectResponse:
    settings = request.app.state.settings
    scratch = settings.upload_dir / secrets.token_hex(8)
    try:
        path = save_upload(file, scratch, settings)
        report = audit_workbook(
            path, settings=settings, filename=sanitize_display_name(file.filename)
        )
        ref = request.app.state.report_store.save(
            kind="audit",
            report_json=to_json(report),
            report_html=render_audit_html(report),
        )
        return RedirectResponse(url=f"/reports/{ref.report_id}", status_code=303)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@router.get("/compare")
def compare_form() -> HTMLResponse:
    return _page("compare.html.j2")


@router.post("/compare")
def compare_submit(
    request: Request, old_file: UploadFile, new_file: UploadFile
) -> RedirectResponse:
    settings = request.app.state.settings
    scratch = settings.upload_dir / secrets.token_hex(8)
    try:
        old_path = save_upload(old_file, scratch, settings)
        new_path = save_upload(new_file, scratch, settings)
        report = compare_workbooks(
            old_path,
            new_path,
            settings=settings,
            old_filename=sanitize_display_name(old_file.filename),
            new_filename=sanitize_display_name(new_file.filename),
        )
        ref = request.app.state.report_store.save(
            kind="comparison",
            report_json=to_json(report),
            report_html=render_comparison_html(report),
        )
        return RedirectResponse(url=f"/reports/{ref.report_id}", status_code=303)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@router.get("/ask")
def ask_form() -> HTMLResponse:
    return _page("ask.html.j2")


_TOKEN_RE = r"^[0-9a-f]{16}$"


def _parked_path(request: Request, token: str):
    import re

    if not re.match(_TOKEN_RE, token or ""):
        return None
    directory = request.app.state.settings.web_upload_dir / token
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*.xls[xm]"))
    return files[0] if files else None


@router.post("/ask")
def ask_submit(
    request: Request,
    file: UploadFile | None = None,
    question: str = Form(...),
    token: str | None = Form(default=None),
    choices: str | None = Form(default=None),
) -> HTMLResponse:
    settings = request.app.state.settings

    # First submission uploads the file; confirmation re-uses the parked copy.
    if token:
        path = _parked_path(request, token)
        if path is None:
            return _page("ask.html.j2", error="Upload expired; please re-submit the file.")
    else:
        if file is None or not file.filename:
            return _page("ask.html.j2", error="Choose a workbook file first.")
        token = secrets.token_hex(8)
        directory = settings.web_upload_dir / token
        path = save_upload(file, directory, settings)

    display_name = sanitize_display_name(getattr(file, "filename", None) or path.name)
    choice_list = [int(c) for c in (choices or "").split(",") if c.strip().isdigit()]

    schema_report = inspect_schema(path, settings=settings, filename=display_name)
    parser = get_parser()
    try:
        query = parser.parse(question, schema_report.workbook_schema)
    except UnsupportedQuestionError as exc:
        shutil.rmtree(path.parent, ignore_errors=True)
        return _page("ask.html.j2", error=str(exc), question=question)

    report = answer_query(
        path,
        query,
        question=question,
        exact_columns=False,
        choices=choice_list,
        settings=settings,
        filename=display_name,
    )
    result = report.result
    if result.status == ResultStatus.NEEDS_CONFIRMATION:
        return _page(
            "ask.html.j2",
            question=question,
            token=token,
            choices=",".join(str(c) for c in choice_list),
            confirmation=result,
        )

    shutil.rmtree(path.parent, ignore_errors=True)
    if result.status == ResultStatus.CANNOT_ANSWER:
        return _page("ask.html.j2", error=result.message, question=question)

    ref = request.app.state.report_store.save(
        kind="query",
        report_json=to_json(report),
        report_html=render_query_html(report),
    )
    return _page(
        "ask.html.j2",
        question=question,
        answered=result,
        report_url=f"/reports/{ref.report_id}",
    )
