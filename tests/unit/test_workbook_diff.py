from pathlib import Path

from conftest import make_workbook
from excel_auditor.analysis.workbook_diff import compare_inventories
from excel_auditor.analysis.workbook_inventory import inventory_from_path
from excel_auditor.models import ChangeType, StructuralChangeType


def _changes_by_key(cell_changes):
    return {(c.sheet_name, c.coordinate): c for c in cell_changes}


def test_demo_diff_detects_planted_changes(old_inventory, new_inventory):
    structural, cell_changes = compare_inventories(old_inventory, new_inventory)
    changes = _changes_by_key(cell_changes)

    # 1: formula overwritten with hardcoded number
    d7 = changes[("Revenue Forecast", "D7")]
    assert d7.change_type == ChangeType.FORMULA_TO_CONSTANT
    assert d7.new_value == 2600

    # 2: wrong-row copy is a formula change
    assert changes[("Cash Flow", "B9")].change_type == ChangeType.FORMULA_CHANGED

    # 3: shrunk total range
    d14 = changes[("Revenue Forecast", "D14")]
    assert d14.change_type == ChangeType.FORMULA_CHANGED
    assert d14.old_formula == "=SUM(D2:D13)"
    assert d14.new_formula == "=SUM(D2:D12)"

    # 6: changed assumption value
    b3 = changes[("Assumptions", "B3")]
    assert b3.change_type == ChangeType.VALUE_CHANGED
    assert b3.old_value == 0.05 and b3.new_value == 0.07

    # 7: formatting-only change
    assert changes[("P&L", "B6")].change_type == ChangeType.FORMATTING_ONLY

    # 10: downstream formula change
    assert changes[("P&L", "B3")].change_type == ChangeType.FORMULA_CHANGED

    # 4: hidden sheet added
    added = [
        c
        for c in structural
        if c.change_type == StructuralChangeType.SHEET_ADDED and c.sheet_name == "Adjustments"
    ]
    assert len(added) == 1
    assert added[0].details["visibility"] == "hidden"

    # 9: volatile formula appears as an added formula
    assert changes[("Summary", "B8")].change_type == ChangeType.FORMULA_ADDED


def test_unchanged_cells_not_reported(old_inventory, new_inventory):
    _, cell_changes = compare_inventories(old_inventory, new_inventory)
    keys = {(c.sheet_name, c.coordinate) for c in cell_changes}
    assert ("Revenue Forecast", "D3") not in keys
    assert ("P&L", "B5") not in keys


def test_sheet_rename_inferred(tmp_path: Path):
    cells = {"A1": "x", "B2": 5, "C3": "=B2*2"}
    old = make_workbook(tmp_path / "old.xlsx", {"Data": dict(cells)})
    new = make_workbook(tmp_path / "new.xlsx", {"Data2024": dict(cells)})
    structural, cell_changes = compare_inventories(
        inventory_from_path(old, workbook_id="old"),
        inventory_from_path(new, workbook_id="new"),
    )
    renames = [c for c in structural if c.change_type == StructuralChangeType.SHEET_RENAMED]
    assert len(renames) == 1
    assert renames[0].details == {"old_name": "Data", "new_name": "Data2024"}
    assert cell_changes == []  # renamed sheet content is identical


def test_sheet_reorder_detected(tmp_path: Path):
    old = make_workbook(tmp_path / "old.xlsx", {"One": {"A1": 1}, "Two": {"A1": 2}})
    new = make_workbook(tmp_path / "new.xlsx", {"Two": {"A1": 2}, "One": {"A1": 1}})
    structural, _ = compare_inventories(
        inventory_from_path(old, workbook_id="old"),
        inventory_from_path(new, workbook_id="new"),
    )
    assert any(c.change_type == StructuralChangeType.SHEETS_REORDERED for c in structural)


def test_constant_to_formula(tmp_path: Path):
    old = make_workbook(tmp_path / "old.xlsx", {"S": {"A1": 10, "A2": 20}})
    new = make_workbook(tmp_path / "new.xlsx", {"S": {"A1": 10, "A2": "=A1*2"}})
    _, cell_changes = compare_inventories(
        inventory_from_path(old, workbook_id="old"),
        inventory_from_path(new, workbook_id="new"),
    )
    changes = _changes_by_key(cell_changes)
    assert changes[("S", "A2")].change_type == ChangeType.CONSTANT_TO_FORMULA
