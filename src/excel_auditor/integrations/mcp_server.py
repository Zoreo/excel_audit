"""MCP server exposing the audit engine to MCP clients (decision D12).

Local-server POC: stdio transport, tool arguments are LOCAL filesystem paths.
Run with::

    python -m excel_auditor.integrations.mcp_server

Tools are thin wrappers over ``services.py`` / ``query_service.py`` (decision
D13: zero analysis logic here). Each tool persists the full report through the
``ReportStore`` public API and returns compact JSON: status, risk level, key
counts, plus the stored report's file paths and URL.

``ask_question`` never bypasses the confirmation flow: when column resolution
is ambiguous it returns the candidate list verbatim and the caller re-invokes
with 1-based ``choices``.

The ``mcp`` SDK is an optional extra (``pip install excel-auditor[mcp]``); it
is imported lazily so importing this module - and the rest of the package -
works without it. Only ``create_server()`` / ``main()`` require it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import query_service, services
from ..config import get_settings
from ..llm import UnsupportedQuestionError, get_parser
from ..models.query import ResultStatus
from ..reporting.html_report import (
    render_audit_html,
    render_comparison_html,
    render_query_html,
    render_schema_html,
)
from ..reporting.json_report import to_json
from ..storage.reports import ReportRef, ReportStore

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

SERVER_NAME = "excel-auditor"


def _missing(path: str) -> dict[str, Any] | None:
    if not Path(path).is_file():
        return {"status": "error", "message": f"File not found: {path}"}
    return None


def _ref_fields(ref: ReportRef) -> dict[str, Any]:
    return {
        "report_id": ref.report_id,
        "report_json_path": str(ref.json_path),
        "report_html_path": str(ref.html_path),
        "report_url": ref.url,
    }


def audit_workbook(path: str) -> dict[str, Any]:
    """Run a standalone risk audit of one workbook (local .xlsx/.xlsm path)."""
    if (error := _missing(path)) is not None:
        return error
    settings = get_settings()
    report = services.audit_workbook(path, settings=settings)
    ref = ReportStore(settings).save(
        kind="audit",
        report_json=to_json(report),
        report_html=render_audit_html(report),
    )
    return {
        "status": "ok",
        "kind": "audit",
        "risk_level": report.risk_level,
        "risk_drivers": report.risk_drivers,
        "finding_count": len(report.findings),
        "findings_by_severity": report.findings_by_severity,
        **_ref_fields(ref),
    }


def compare_workbooks(old_path: str, new_path: str) -> dict[str, Any]:
    """Compare two versions of a workbook (local paths: old, new)."""
    for candidate in (old_path, new_path):
        if (error := _missing(candidate)) is not None:
            return error
    settings = get_settings()
    report = services.compare_workbooks(old_path, new_path, settings=settings)
    ref = ReportStore(settings).save(
        kind="comparison",
        report_json=to_json(report),
        report_html=render_comparison_html(report),
    )
    return {
        "status": "ok",
        "kind": "comparison",
        "risk_level": report.risk_level,
        "risk_drivers": report.risk_drivers,
        "total_cell_changes": report.summary.total_cell_changes,
        "total_review_items": report.summary.total_review_items,
        "high_impact_changes": report.summary.high_impact_changes,
        "structural_change_count": report.summary.structural_change_count,
        **_ref_fields(ref),
    }


def inspect_schema(path: str) -> dict[str, Any]:
    """Detect sheets, tables and column types of a workbook (local path)."""
    if (error := _missing(path)) is not None:
        return error
    settings = get_settings()
    report = query_service.inspect_schema(path, settings=settings)
    ref = ReportStore(settings).save(
        kind="schema",
        report_json=to_json(report),
        report_html=render_schema_html(report),
    )
    schema = report.workbook_schema
    return {
        "status": "ok",
        "kind": "schema",
        "sheet_count": len(schema.sheets),
        "tables": [
            {
                "sheet": table.sheet_name,
                "ref": table.ref,
                "rows": table.row_count,
                "columns": [
                    {"name": column.name, "type": column.type.value}
                    for column in table.columns
                ],
            }
            for table in schema.tables
        ],
        **_ref_fields(ref),
    }


def ask_question(
    path: str, question: str, choices: list[int] | None = None
) -> dict[str, Any]:
    """Answer a constrained free-text question about a workbook (local path).

    Ambiguity is never resolved silently: a ``needs_confirmation`` result
    carries the candidate columns verbatim; re-invoke with the 1-based
    ``choices`` list to confirm (one entry per ambiguity, in order).
    """
    if (error := _missing(path)) is not None:
        return error
    settings = get_settings()
    schema = query_service.inspect_schema(path, settings=settings).workbook_schema
    try:
        query = get_parser().parse(question, schema)
    except UnsupportedQuestionError as exc:
        return {"status": ResultStatus.CANNOT_ANSWER.value, "message": str(exc)}

    report = query_service.answer_query(
        path,
        query,
        question=question,
        exact_columns=False,
        choices=choices,
        settings=settings,
    )
    result = report.result
    payload: dict[str, Any] = {
        "status": result.status.value,
        "kind": "query",
        "message": result.message,
    }
    if result.status == ResultStatus.NEEDS_CONFIRMATION:
        # Candidates verbatim (decision D12): the caller shows them to the
        # user and re-invokes with `choices`.
        payload["candidate_kind"] = result.candidate_kind
        payload["candidates"] = [
            candidate.model_dump() for candidate in result.candidates
        ]
        return payload
    if result.status == ResultStatus.CANNOT_ANSWER:
        return payload

    ref = ReportStore(settings).save(
        kind="query",
        report_json=to_json(report),
        report_html=render_query_html(report),
    )
    payload["value"] = json.loads(result.model_dump_json())["value"]
    payload["row_count"] = len(result.rows)
    payload.update(_ref_fields(ref))
    return payload


def create_server() -> FastMCP:
    """Build the FastMCP server with the four D12 tools registered.

    Tools read Settings from the environment on every call, so the process
    needs no configuration beyond the standard EXCEL_AUDITOR_* variables.
    """
    # Lazy import: the mcp SDK is the optional [mcp] extra.
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(SERVER_NAME)
    server.tool()(audit_workbook)
    server.tool()(compare_workbooks)
    server.tool()(inspect_schema)
    server.tool()(ask_question)
    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
