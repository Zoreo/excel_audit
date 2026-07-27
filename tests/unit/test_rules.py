from pathlib import Path

from conftest import make_workbook
from excel_auditor.analysis.dependency_graph import DependencyGraph
from excel_auditor.analysis.pattern_detection import detect_pattern_anomalies
from excel_auditor.analysis.rules import AuditContext, run_all_rules
from excel_auditor.analysis.workbook_inventory import inventory_from_path
from excel_auditor.models import Severity, WorkbookInventory


def _run(inventory: WorkbookInventory):
    graph = DependencyGraph.build(inventory)
    anomalies = detect_pattern_anomalies(inventory)
    return run_all_rules(
        AuditContext(inventory=inventory, graph=graph, pattern_anomalies=anomalies)
    )


def test_demo_v2_fires_expected_rules(new_inventory):
    findings = _run(new_inventory)
    fired = {f.rule_id for f in findings}
    assert "EA-HID-001" in fired  # hidden 'Adjustments' sheet
    assert "EA-HID-002" in fired  # hidden row/col with data on Assumptions
    assert "EA-EXT-001" in fired  # external dependency (formula reference)
    assert "EA-REF-001" in fired  # #REF!
    assert "EA-VOL-001" in fired  # TODAY()
    assert "EA-PAT-001" in fired  # overwritten formula
    assert "EA-PAT-002" in fired  # wrong-row copy
    assert "EA-RNG-001" in fired  # total excludes final month
    assert "EA-HRD-001" in fired  # 0.9 / 0.45 hardcoded in formulas
    assert "EA-RND-001" in fired  # Фактури rounding drift (displayed sums differ)


def test_demo_v1_quieter_than_v2(old_inventory, new_inventory):
    v1 = {f.rule_id for f in _run(old_inventory)}
    v2 = {f.rule_id for f in _run(new_inventory)}
    for rule_id in ("EA-PAT-001", "EA-PAT-002", "EA-REF-001", "EA-VOL-001", "EA-EXT-001"):
        assert rule_id not in v1
        assert rule_id in v2


def test_external_count_consistent_with_inventory(new_inventory):
    """Fix: the overview count and the rule's evidence use the same universe."""
    assert "Benchmarks.xlsx" in new_inventory.external_links
    findings = [f for f in _run(new_inventory) if f.rule_id == "EA-EXT-001"]
    assert len(findings) == 1
    assert findings[0].evidence["targets"] == new_inventory.external_links


def test_repeated_low_severity_findings_grouped(tmp_path: Path):
    """Fix: 6 TODAY() cells collapse into one grouped finding."""
    cells = {f"A{r}": "=TODAY()" for r in range(1, 7)}
    path = make_workbook(tmp_path / "volatile.xlsx", {"S": cells})
    findings = [f for f in _run(inventory_from_path(path)) if f.rule_id == "EA-VOL-001"]
    assert len(findings) == 1
    grouped = findings[0]
    assert grouped.evidence["count"] == 6
    assert grouped.location is not None and grouped.location.coordinate is None
    assert len(grouped.related_locations) == 6
    assert "6 cells" in grouped.title


def test_suspicious_range_flags_excluded_row(new_inventory):
    findings = [f for f in _run(new_inventory) if f.rule_id == "EA-RNG-001"]
    assert any(
        f.location is not None
        and f.location.sheet_name == "Revenue Forecast"
        and f.location.coordinate == "D14"
        and f.evidence.get("excluded_cell") == "D13"
        for f in findings
    )


def test_suspicious_range_quiet_when_total_is_adjacent(old_inventory):
    # v1: SUM(D2:D13) sits directly in D14 -> no finding
    assert all(f.rule_id != "EA-RNG-001" for f in _run(old_inventory))


def test_error_value_severities(tmp_path: Path):
    path = make_workbook(
        tmp_path / "errors.xlsx",
        {"S": {"A1": "#DIV/0!", "A2": "#N/A"}},
    )
    findings = [f for f in _run(inventory_from_path(path)) if f.rule_id == "EA-ERR-001"]
    by_cell = {f.location.coordinate: f for f in findings if f.location}
    assert by_cell["A1"].severity == Severity.HIGH
    assert by_cell["A2"].severity == Severity.LOW


def test_circular_reference_rule(tmp_path: Path):
    path = make_workbook(
        tmp_path / "cycle.xlsx", {"Loop": {"A1": "=B1+1", "B1": "=A1+1"}}
    )
    findings = [f for f in _run(inventory_from_path(path)) if f.rule_id == "EA-CIR-001"]
    assert len(findings) == 1
    assert findings[0].evidence["cycle_size"] == 2


def test_self_referencing_circular_rule(tmp_path: Path):
    path = make_workbook(
        tmp_path / "selfcycle.xlsx",
        {
            "Loop": {
                "A1": "=A1+1",
                **{f"D{r}": r for r in range(1, 11)},
                "D11": "=SUM(D1:D11)",
            }
        },
    )
    findings = [f for f in _run(inventory_from_path(path)) if f.rule_id == "EA-CIR-001"]
    assert len(findings) == 2
    members = {tuple(f.evidence["members"]) for f in findings}
    assert members == {("Loop!A1",), ("Loop!D11",)}
    assert all(f.evidence["cycle_size"] == 1 for f in findings)


def test_blank_reference_rule(tmp_path: Path):
    path = make_workbook(
        tmp_path / "blankref.xlsx",
        {"S": {"A1": "=B1+C1", "C1": 2, "B3": 5}},  # B1 blank but inside used range
    )
    findings = [f for f in _run(inventory_from_path(path)) if f.rule_id == "EA-RNG-002"]
    assert len(findings) == 1
    examples = findings[0].evidence["examples"]
    assert any(e["references_blank"] == "S!B1" for e in examples)


def test_findings_sorted_by_severity(new_inventory):
    findings = _run(new_inventory)
    from excel_auditor.models.enums import SEVERITY_ORDER

    ranks = [SEVERITY_ORDER[f.severity] for f in findings]
    assert ranks == sorted(ranks, reverse=True)
