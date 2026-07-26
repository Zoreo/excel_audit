import json
from pathlib import Path

from conftest import make_workbook
from excel_auditor.reporting.html_report import render_audit_html, render_comparison_html
from excel_auditor.reporting.json_report import to_json
from excel_auditor.services import audit_workbook, compare_workbooks


def test_audit_json_round_trip(demo_paths):
    report = audit_workbook(demo_paths[1])
    payload = json.loads(to_json(report))
    assert payload["engine_version"]
    assert payload["risk_level"] == "high"  # v2 plants several high-severity issues
    assert payload["risk_drivers"]
    assert payload["workbook"]["sheets"]
    assert payload["findings"]
    for finding in payload["findings"]:
        assert finding["rule_id"]
        assert finding["severity"] in {"info", "low", "medium", "high", "critical"}
        assert finding["confidence"] in {"low", "medium", "high"}


def test_report_schema_version_present_in_json(demo_paths):
    audit_payload = json.loads(to_json(audit_workbook(demo_paths[1])))
    assert audit_payload["report_schema_version"] == "3"
    comparison_payload = json.loads(to_json(compare_workbooks(*demo_paths)))
    assert comparison_payload["report_schema_version"] == "3"


def test_comparison_json_includes_impact(demo_paths):
    report = compare_workbooks(*demo_paths)
    payload = json.loads(to_json(report))
    changes = {
        (c["sheet_name"], c["coordinate"]): c for c in payload["cell_changes"]
    }
    b3 = changes[("P&L", "B3")]
    assert b3["downstream_impact"]["transitive_dependent_count"] > 3
    assert b3["downstream_impact"]["touches_outputs"] is True
    assert payload["summary"]["total_cell_changes"] == len(payload["cell_changes"])


def test_review_items_unify_changes_and_findings(demo_paths):
    """Fixes: no duplicate reporting, and diff severity agrees with findings."""
    report = compare_workbooks(*demo_paths)

    # No two review items share a cell location.
    located = [
        (i.sheet_name, i.coordinate) for i in report.review_items if i.coordinate
    ]
    assert len(located) == len(set(located))

    by_key = {(i.sheet_name, i.coordinate): i for i in report.review_items}

    # D7: FORMULA_TO_CONSTANT change + EA-PAT-001 finding -> one item.
    d7 = by_key[("Revenue Forecast", "D7")]
    assert d7.change is not None and d7.findings
    assert {f.rule_id for f in d7.findings} == {"EA-PAT-001"}

    # D14: the change and the EA-RNG-001 finding reconcile to the same severity.
    d14 = by_key[("Revenue Forecast", "D14")]
    assert any(f.rule_id == "EA-RNG-001" for f in d14.findings)
    assert d14.change is not None
    assert d14.change.severity == d14.severity  # written back (reconciled)

    # The raw cell_changes list agrees with the unified items everywhere.
    changes = {(c.sheet_name, c.coordinate): c for c in report.cell_changes}
    for key, item in by_key.items():
        if item.change is not None:
            assert changes[key].severity == item.severity

    # The #REF! formula added in v2 gets the finding's HIGH severity, not the
    # low base severity of "formula added".
    d2 = by_key[("Cash Flow", "D2")]
    assert d2.severity.value == "high"


def test_risk_level_is_transparent(demo_paths):
    report = compare_workbooks(*demo_paths)
    assert report.risk_level == "high"
    # the level is exactly the highest severity present among review items
    top = max(
        (i.severity.value for i in report.review_items),
        key=lambda s: ["info", "low", "medium", "high", "critical"].index(s),
    )
    assert top == "high"
    assert any("high-severity" in d for d in report.risk_drivers)


def test_html_reports_render(demo_paths):
    audit_html = render_audit_html(audit_workbook(demo_paths[1]))
    assert "<html" in audit_html
    assert "Workbook Risk Audit" in audit_html
    assert "Adjustments" in audit_html  # hidden sheet named in findings
    assert "Risk level" in audit_html

    comparison_html = render_comparison_html(compare_workbooks(*demo_paths))
    assert "Workbook Comparison" in comparison_html
    assert "Review items" in comparison_html
    assert "highest severity present" in comparison_html
    assert "Limitations" in comparison_html


def test_html_escapes_workbook_content(tmp_path: Path):
    hostile = "<script>alert('x')</script>"
    old = make_workbook(tmp_path / "old.xlsx", {"S": {"A1": "safe"}})
    new = make_workbook(tmp_path / "new.xlsx", {"S": {"A1": hostile}})
    html = render_comparison_html(compare_workbooks(old, new))
    assert hostile not in html
    assert "&lt;script&gt;" in html
