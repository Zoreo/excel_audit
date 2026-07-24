"""Cross-fix interaction tests (lead-owned, per the remediation plan).

Each test exercises two independently fixed findings together to prove the
fixes compose: a wrong answer prevented by one fix must stay prevented when
the code path of another fix is also in play.
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from excel_auditor.llm.rule_parser import RuleBasedIntentParser
from excel_auditor.models.query import FilterOperator, ResultStatus
from excel_auditor.query_service import answer_query, inspect_schema


def _duplicate_amount_workbook(path: Path) -> Path:
    """Category|Amount|Amount with divergent data in the two Amount columns."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    for col, name in enumerate(["Category", "Amount", "Amount"], start=1):
        ws.cell(row=1, column=col, value=name).font = Font(bold=True)
    rows = [("a", 100, 1000), ("b", 200, 2000), ("c", 700, 7000), ("d", 900, 9000)]
    for i, (category, first, second) in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=category)
        ws.cell(row=i, column=2, value=first)
        ws.cell(row=i, column=3, value=second)
    wb.save(path)
    return path


def test_threshold_query_on_duplicate_headers_confirms_then_filters_chosen_column(
    tmp_path,
):
    """QA-001 x QA-002: a threshold question against duplicate headers must
    first surface the ambiguity, then filter the CHOSEN physical column."""
    path = _duplicate_amount_workbook(tmp_path / "dup_threshold.xlsx")

    parser = RuleBasedIntentParser()
    schema = inspect_schema(path).workbook_schema
    query = parser.parse("show rows where amount over 500", schema)

    # QA-002: the threshold filter must be built, not silently dropped.
    assert [(f.column, f.operator, f.value) for f in query.filters] == [
        ("amount", FilterOperator.GREATER_THAN, 500.0)
    ]

    # QA-001: two physical Amount columns -> never resolved silently.
    first = answer_query(path, query, exact_columns=False)
    assert first.result.status == ResultStatus.NEEDS_CONFIRMATION
    labels = [c.column_name for c in first.result.candidates]
    assert labels == ["Amount (column B)", "Amount (column C)"]

    # Column B: 100/200/700/900 -> two rows exceed 500.
    chose_b = answer_query(path, query, exact_columns=False, choices=[1])
    assert chose_b.result.status == ResultStatus.VERIFIED
    assert chose_b.result.provenance.rows_included == 2
    assert any("500" in f for f in chose_b.result.provenance.filters)

    # Column C: 1000/2000/7000/9000 -> every row exceeds 500.
    chose_c = answer_query(path, query, exact_columns=False, choices=[2])
    assert chose_c.result.status == ResultStatus.VERIFIED
    assert chose_c.result.provenance.rows_included == 4
