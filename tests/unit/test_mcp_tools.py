"""MCP tool tests (decision D12).

The `mcp` SDK is an optional extra, so this whole module is skipped when it
is not installed; the core suite never depends on it. Everything runs
in-process and offline - the stdio transport is never started.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from excel_auditor.integrations import mcp_server  # noqa: E402

BG_QUESTION = "Какъв е общият оборот за 2025?"


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reports produced by tool calls land in a per-test scratch area."""
    monkeypatch.setenv("EXCEL_AUDITOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EXCEL_AUDITOR_ARTIFACTS_DIR", str(tmp_path / "artifacts"))


def _assert_report_persisted(result: dict) -> None:
    json_path = Path(result["report_json_path"])
    html_path = Path(result["report_html_path"])
    assert json_path.is_file()
    assert html_path.is_file()
    assert result["report_url"].startswith("http")
    assert result["report_id"] in result["report_url"]
    json.loads(json_path.read_text(encoding="utf-8"))  # stored JSON is valid


# --------------------------------------------------------------- tool logic


def test_audit_workbook_returns_risk_and_report_path(demo_paths):
    _, v2 = demo_paths
    result = mcp_server.audit_workbook(str(v2))
    assert result["status"] == "ok"
    assert result["kind"] == "audit"
    assert result["risk_level"] in {"high", "critical"}
    assert result["finding_count"] > 0
    assert result["findings_by_severity"]
    _assert_report_persisted(result)


def test_compare_workbooks_returns_counts_and_report(demo_paths):
    v1, v2 = demo_paths
    result = mcp_server.compare_workbooks(str(v1), str(v2))
    assert result["status"] == "ok"
    assert result["kind"] == "comparison"
    assert result["total_cell_changes"] > 0
    assert result["total_review_items"] > 0
    assert result["risk_level"] in {"minimal", "low", "medium", "high", "critical"}
    _assert_report_persisted(result)


def test_inspect_schema_lists_tables(sales_bg):
    result = mcp_server.inspect_schema(str(sales_bg))
    assert result["status"] == "ok"
    assert result["sheet_count"] >= 1
    (table,) = result["tables"]
    assert table["sheet"] == "Sales"
    names = [column["name"] for column in table["columns"]]
    assert "Оборот" in names
    assert "Нетен оборот" in names
    _assert_report_persisted(result)


def test_missing_path_is_reported_not_raised(tmp_path):
    for result in (
        mcp_server.audit_workbook(str(tmp_path / "missing.xlsx")),
        mcp_server.compare_workbooks(str(tmp_path / "a.xlsx"), str(tmp_path / "b.xlsx")),
        mcp_server.inspect_schema(str(tmp_path / "missing.xlsx")),
        mcp_server.ask_question(str(tmp_path / "missing.xlsx"), BG_QUESTION),
    ):
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()


# ------------------------------------------------- ask_question confirmation


def test_ask_question_surfaces_candidates_then_answers(sales_bg):
    first = mcp_server.ask_question(str(sales_bg), BG_QUESTION)
    assert first["status"] == "needs_confirmation"
    assert first["candidate_kind"] == "value_column"
    names = [candidate["column_name"] for candidate in first["candidates"]]
    assert names == ["Оборот", "Нетен оборот"]
    # No report is persisted for an unconfirmed query.
    assert "report_id" not in first

    confirmed = mcp_server.ask_question(str(sales_bg), BG_QUESTION, choices=[1])
    # Blank revenue cells downgrade "verified" to "review_recommended";
    # both are answered states with a persisted report.
    assert confirmed["status"] in {"verified", "review_recommended"}
    assert confirmed["value"] == 628400
    _assert_report_persisted(confirmed)

    net = mcp_server.ask_question(str(sales_bg), BG_QUESTION, choices=[2])
    assert net["value"] == 565560


def test_ask_question_rejects_open_ended(sales_bg):
    result = mcp_server.ask_question(str(sales_bg), "Find fraud.")
    assert result["status"] == "cannot_answer_safely"
    assert "report_id" not in result


# --------------------------------------------------- FastMCP server wiring


def test_create_server_registers_the_four_tools():
    server = mcp_server.create_server()
    tools = asyncio.run(server.list_tools())
    assert sorted(tool.name for tool in tools) == [
        "ask_question",
        "audit_workbook",
        "compare_workbooks",
        "inspect_schema",
    ]


def _call_tool(server, name: str, arguments: dict) -> dict:
    contents = asyncio.run(server.call_tool(name, arguments))
    if isinstance(contents, tuple):  # newer SDKs: (content, structured)
        contents = contents[0]
    (content,) = contents
    return json.loads(content.text)


def test_fastmcp_in_process_tool_invocation(demo_paths):
    _, v2 = demo_paths
    server = mcp_server.create_server()
    result = _call_tool(server, "audit_workbook", {"path": str(v2)})
    assert result["status"] == "ok"
    assert result["risk_level"] in {"high", "critical"}
    assert Path(result["report_json_path"]).is_file()


def test_fastmcp_ask_question_confirmation_roundtrip(sales_bg):
    server = mcp_server.create_server()
    first = _call_tool(server, "ask_question", {"path": str(sales_bg), "question": BG_QUESTION})
    assert first["status"] == "needs_confirmation"
    assert len(first["candidates"]) == 2

    confirmed = _call_tool(
        server,
        "ask_question",
        {"path": str(sales_bg), "question": BG_QUESTION, "choices": [1]},
    )
    assert confirmed["status"] in {"verified", "review_recommended"}
    assert confirmed["value"] == 628400
