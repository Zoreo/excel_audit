"""POST /api/v1/queries - deterministic structured or free-text queries.

Accepts multipart form data:
  file      the workbook (.xlsx/.xlsm)
  query     JSON-encoded SpreadsheetQuery (structured mode), or
  question  free text routed through the configured intent parser
  choices   optional comma-separated 1-based answers to earlier
            needs_confirmation responses
"""

from __future__ import annotations

import json
import shutil
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError

from ...llm import UnsupportedQuestionError, get_parser
from ...models.query import QueryAction, ResultStatus, SpreadsheetQuery
from ...query_service import answer_query, inspect_schema
from ...reporting.html_report import render_query_html
from ...reporting.json_report import to_json
from ..uploads import sanitize_display_name, save_upload

router = APIRouter()


def _parse_choices(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        return [int(part) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="choices must be integers") from exc


@router.post("/api/v1/queries", status_code=200)
def create_query(
    request: Request,
    file: UploadFile,
    query: str | None = Form(default=None),
    question: str | None = Form(default=None),
    choices: str | None = Form(default=None),
) -> dict:
    if not query and not question:
        raise HTTPException(
            status_code=422, detail="Provide either 'query' (JSON) or 'question' (text)."
        )
    settings = request.app.state.settings
    display_name = sanitize_display_name(file.filename)
    scratch = settings.upload_dir / uuid4().hex
    try:
        path = save_upload(file, scratch, settings)

        exact = query is not None
        if query is not None:
            try:
                structured = SpreadsheetQuery.model_validate(json.loads(query))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise HTTPException(
                    status_code=422, detail=f"Invalid structured query: {exc}"
                ) from exc
        else:
            schema_report = inspect_schema(path, settings=settings, filename=display_name)
            parser = get_parser()
            try:
                structured = parser.parse(question or "", schema_report.workbook_schema)
            except UnsupportedQuestionError as exc:
                return {"status": ResultStatus.CANNOT_ANSWER.value, "message": str(exc)}
        if structured.action not in (QueryAction.QUERY_TABLE, QueryAction.INSPECT_WORKBOOK,
                                     QueryAction.TRACE_DEPENDENCIES):
            raise HTTPException(
                status_code=422,
                detail=f"Action '{structured.action.value}' has its own endpoint.",
            )

        report = answer_query(
            path,
            structured,
            question=question,
            exact_columns=exact,
            choices=_parse_choices(choices),
            settings=settings,
            filename=display_name,
        )
        payload: dict = {
            "status": report.result.status.value,
            "result": json.loads(report.result.model_dump_json()),
        }
        if report.result.status not in (
            ResultStatus.NEEDS_CONFIRMATION,
            ResultStatus.CANNOT_ANSWER,
        ):
            ref = request.app.state.report_store.save(
                kind="query",
                report_json=to_json(report),
                report_html=render_query_html(report),
            )
            payload["report_id"] = ref.report_id
            payload["report_url"] = ref.url
        return payload
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
