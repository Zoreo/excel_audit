"""EXCEL-003 interim marker: unresolved defined-name/table tokens must mark
impact as potentially understated instead of a confident zero."""

from pathlib import Path
from typing import Any

from conftest import make_workbook
from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName

from excel_auditor.analysis.dependency_graph import DependencyGraph, impact_for
from excel_auditor.analysis.severity import classify_cell_change
from excel_auditor.analysis.workbook_inventory import inventory_from_path
from excel_auditor.models import ChangeType, Confidence, DependencyImpact, Severity


def _workbook_with_defined_name(
    path: Path, cells: dict[str, Any], name: str, refers_to: str
) -> Path:
    """Single-sheet workbook ('Model') with one workbook-scoped defined name."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Model"
    for coordinate, value in cells.items():
        ws[coordinate] = value
    wb.defined_names.add(DefinedName(name, attr_text=refers_to))
    wb.save(path)
    return path


def test_defined_name_formula_marks_impact_unknown(tmp_path: Path):
    path = _workbook_with_defined_name(
        tmp_path / "named.xlsx",
        {"A1": 100, "B1": "=MyInput*2", "C1": "=B1+1"},
        "MyInput",
        "Model!$A$1",
    )
    inventory = inventory_from_path(path)
    graph = DependencyGraph.build(inventory)
    assert graph.unresolved_name_cells == {("Model", "B1")}

    # The name's target: dependents are invisible until T4b, so the zero must
    # carry the unknown marker, never full confidence.
    impact = impact_for(graph, inventory, ("Model", "A1"))
    assert impact.transitive_dependent_count == 0
    assert impact.has_unresolved_names

    severity, confidence = classify_cell_change(ChangeType.VALUE_CHANGED, impact=impact)
    assert severity == Severity.LOW  # no aggressive escalation ...
    assert confidence == Confidence.MEDIUM  # ... but no confident "low impact"


def test_structured_table_reference_marks_impact_unknown(tmp_path: Path):
    path = make_workbook(
        tmp_path / "table.xlsx",
        {"Data": {"A1": 1, "A2": 2, "B1": "=SUM(Table1[Amount])"}},
    )
    inventory = inventory_from_path(path)
    graph = DependencyGraph.build(inventory)
    assert graph.unresolved_name_cells == {("Data", "B1")}
    assert impact_for(graph, inventory, ("Data", "A1")).has_unresolved_names


def test_no_defined_names_no_marker(tmp_path: Path):
    path = make_workbook(
        tmp_path / "plain.xlsx",
        {"Model": {"A1": 100, "B1": "=A1*2", "C1": "=B1+1"}},
    )
    inventory = inventory_from_path(path)
    graph = DependencyGraph.build(inventory)
    assert not graph.unresolved_name_cells

    impact = impact_for(graph, inventory, ("Model", "A1"))
    assert not impact.has_unresolved_names
    assert impact.transitive_dependent_count == 2

    severity, confidence = classify_cell_change(ChangeType.VALUE_CHANGED, impact=impact)
    assert severity == Severity.LOW
    assert confidence == Confidence.HIGH  # no false alarm


def test_demonstrated_impact_still_escalates_with_full_confidence():
    # When the escalation already fired, the classification is not understated:
    # severity goes up as before and confidence stays high.
    impact = DependencyImpact(
        transitive_dependent_count=25, has_unresolved_names=True
    )
    severity, confidence = classify_cell_change(ChangeType.VALUE_CHANGED, impact=impact)
    assert severity == Severity.MEDIUM
    assert confidence == Confidence.HIGH
