"""Row-insertion inference in the workbook diff (milestone-3 T11, D7/D8).

Rows of a matched sheet pair are aligned by per-row signatures with
difflib.SequenceMatcher when the sheet has >= 5 data rows on both sides and
the match ratio is >= 0.60. Inserted/removed rows collapse into
ROWS_INSERTED / ROWS_REMOVED structural changes (one per contiguous run,
with up to 5 sample cell previews) instead of flooding the report with
per-cell adds/removes; aligned rows diff at their aligned coordinates.
Below-gate sheets keep the legacy positional diff.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import make_workbook
from excel_auditor.analysis.workbook_diff import compare_inventories
from excel_auditor.analysis.workbook_inventory import inventory_from_path
from excel_auditor.models import ChangeType, StructuralChangeType
from excel_auditor.services import compare_workbooks


def _diff(old_path: Path, new_path: Path):
    return compare_inventories(
        inventory_from_path(old_path, workbook_id="old"),
        inventory_from_path(new_path, workbook_id="new"),
    )


def _row_changes(structural, change_type):
    return [c for c in structural if c.change_type == change_type]


def _change_tuples(cell_changes):
    return [(c.sheet_name, c.coordinate, c.change_type) for c in cell_changes]


def _ledger(
    items: list[tuple[str, int]], *, total: bool = True
) -> dict[str, Any]:
    """Header + one row per item (label, units, doubling formula) + total."""
    cells: dict[str, Any] = {"A1": "Item", "B1": "Units", "C1": "Value"}
    for offset, (label, units) in enumerate(items):
        row = offset + 2
        cells[f"A{row}"] = label
        cells[f"B{row}"] = units
        cells[f"C{row}"] = f"=B{row}*2"
    if total:
        total_row = len(items) + 2
        cells[f"A{total_row}"] = "Total"
        cells[f"C{total_row}"] = f"=SUM(C2:C{total_row - 1})"
    return cells


_BASE_ITEMS = [(f"Item {i}", 100 + i) for i in range(1, 11)]  # rows 2..11


# ------------------------------------------------- acceptance 1: collapse


def test_mid_table_insertion_collapses(tmp_path: Path):
    """One row inserted mid-table: exactly one ROWS_INSERTED, the grown total
    range as a formula change at its shifted position, zero add flood."""
    new_items = list(_BASE_ITEMS)
    new_items.insert(4, ("Item X", 999))  # lands on row 6, shifts rows 6..12
    old = make_workbook(tmp_path / "old.xlsx", {"Data": _ledger(_BASE_ITEMS)})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": _ledger(new_items)})

    structural, cell_changes = _diff(old, new)

    inserted = _row_changes(structural, StructuralChangeType.ROWS_INSERTED)
    assert len(inserted) == 1
    assert inserted[0].sheet_name == "Data"
    assert inserted[0].details["start_row"] == 6
    assert inserted[0].details["count"] == 1
    sampled = {s["coordinate"]: s for s in inserted[0].details["sample_cells"]}
    assert sampled["A6"]["value"] == "Item X"
    assert sampled["C6"]["formula"] == "=B6*2"
    assert _row_changes(structural, StructuralChangeType.ROWS_REMOVED) == []

    # Only the total's range grew; everything shifted is silent.
    assert _change_tuples(cell_changes) == [("Data", "C13", ChangeType.FORMULA_CHANGED)]
    assert cell_changes[0].old_formula == "=SUM(C2:C11)"
    assert cell_changes[0].new_formula == "=SUM(C2:C12)"


def test_review_items_reflect_the_collapse(tmp_path: Path):
    """Full-service comparison: summaries count the structural change and the
    review list contains no add flood from the shifted rows."""
    new_items = list(_BASE_ITEMS)
    new_items.insert(4, ("Item X", 999))
    old = make_workbook(tmp_path / "old.xlsx", {"Data": _ledger(_BASE_ITEMS)})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": _ledger(new_items)})

    report = compare_workbooks(old, new)

    assert report.summary.total_cell_changes == 1
    assert report.summary.changes_by_type == {"formula_changed": 1}
    assert report.summary.structural_change_count == 1
    assert report.structural_changes[0].change_type == StructuralChangeType.ROWS_INSERTED
    assert not [
        i
        for i in report.review_items
        if i.change is not None
        and i.change.change_type in {ChangeType.VALUE_ADDED, ChangeType.FORMULA_ADDED}
    ]


# ------------------------------------------- acceptance 2: insert + edit


def test_insert_plus_edit_reports_edit_at_aligned_coordinate(tmp_path: Path):
    new_items = list(_BASE_ITEMS)
    new_items.insert(4, ("Item X", 999))  # row 6
    new_items[7] = ("Item 7", 4242)  # was 107 on old row 8; shifted to row 9
    old = make_workbook(tmp_path / "old.xlsx", {"Data": _ledger(_BASE_ITEMS)})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": _ledger(new_items)})

    structural, cell_changes = _diff(old, new)

    inserted = _row_changes(structural, StructuralChangeType.ROWS_INSERTED)
    assert len(inserted) == 1
    assert inserted[0].details["start_row"] == 6
    assert inserted[0].details["count"] == 1

    changes = {(c.sheet_name, c.coordinate): c for c in cell_changes}
    # "Item 7" (units 107) sat on old row 8; after the insertion it is row 9.
    edited = changes[("Data", "B9")]
    assert edited.change_type == ChangeType.VALUE_CHANGED
    assert edited.old_value == 107
    assert edited.new_value == 4242
    # ...and the only other change is the grown total range.
    assert set(changes) == {("Data", "B9"), ("Data", "C13")}
    assert changes[("Data", "C13")].change_type == ChangeType.FORMULA_CHANGED


# ---------------------------------------------- acceptance 3: row removed


def test_deleted_row_collapses_symmetrically(tmp_path: Path):
    old_items = list(_BASE_ITEMS)
    old_items.insert(4, ("Item X", 999))  # old row 6, deleted in the new version
    old = make_workbook(tmp_path / "old.xlsx", {"Data": _ledger(old_items)})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": _ledger(_BASE_ITEMS)})

    structural, cell_changes = _diff(old, new)

    removed = _row_changes(structural, StructuralChangeType.ROWS_REMOVED)
    assert len(removed) == 1
    assert removed[0].sheet_name == "Data"
    assert removed[0].details["start_row"] == 6  # old-version row number
    assert removed[0].details["count"] == 1
    sampled = {s["coordinate"]: s for s in removed[0].details["sample_cells"]}
    assert sampled["A6"]["value"] == "Item X"
    assert sampled["B6"]["value"] == 999
    assert _row_changes(structural, StructuralChangeType.ROWS_INSERTED) == []

    assert _change_tuples(cell_changes) == [("Data", "C12", ChangeType.FORMULA_CHANGED)]
    assert cell_changes[0].old_formula == "=SUM(C2:C12)"
    assert cell_changes[0].new_formula == "=SUM(C2:C11)"


# ------------------------------------- acceptance 4: gate failures fall back


def test_below_gate_sheet_keeps_positional_diff(tmp_path: Path):
    """4 data rows: alignment never engages; the insertion floods positionally
    exactly as before schema v3."""
    old = make_workbook(
        tmp_path / "old.xlsx",
        {"Data": {"A2": 10, "A3": 20, "A4": 30, "A5": 40}},
    )
    new = make_workbook(
        tmp_path / "new.xlsx",
        {"Data": {"A2": 10, "A3": 99, "A4": 20, "A5": 30, "A6": 40}},
    )

    structural, cell_changes = _diff(old, new)

    assert _row_changes(structural, StructuralChangeType.ROWS_INSERTED) == []
    assert _row_changes(structural, StructuralChangeType.ROWS_REMOVED) == []
    assert _change_tuples(cell_changes) == [
        ("Data", "A3", ChangeType.VALUE_CHANGED),
        ("Data", "A4", ChangeType.VALUE_CHANGED),
        ("Data", "A5", ChangeType.VALUE_CHANGED),
        ("Data", "A6", ChangeType.VALUE_ADDED),
    ]


def test_dissimilar_sheets_keep_positional_diff(tmp_path: Path):
    """Ratio < 0.60: sheets sharing a name but not content diff positionally."""
    old_cells = {f"A{r}": r * 10 for r in range(2, 9)}
    new_cells = {f"B{r}": f"note {r}" for r in range(2, 12)}
    old = make_workbook(tmp_path / "old.xlsx", {"Data": old_cells})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": new_cells})

    structural, cell_changes = _diff(old, new)

    assert _row_changes(structural, StructuralChangeType.ROWS_INSERTED) == []
    assert _row_changes(structural, StructuralChangeType.ROWS_REMOVED) == []
    by_type = {c.change_type for c in cell_changes}
    assert by_type == {ChangeType.VALUE_REMOVED, ChangeType.VALUE_ADDED}
    assert len(cell_changes) == 17  # 7 removals + 10 additions, cell by cell


def test_pure_row_reorder_keeps_positional_diff(tmp_path: Path):
    """Swapped rows are a move, not an insertion: fall back so the swap reads
    as value changes at the swapped positions."""
    def build(path: Path, units: list[int]) -> Path:
        cells: dict[str, Any] = {}
        for offset, value in enumerate(units):
            row = offset + 2
            cells[f"B{row}"] = value
            cells[f"C{row}"] = f"=B{row}*2"
        return make_workbook(path, {"Data": cells})

    old = build(tmp_path / "old.xlsx", [10, 20, 30, 40, 50, 60])
    new = build(tmp_path / "new.xlsx", [20, 10, 30, 40, 50, 60])

    structural, cell_changes = _diff(old, new)

    assert _row_changes(structural, StructuralChangeType.ROWS_INSERTED) == []
    assert _row_changes(structural, StructuralChangeType.ROWS_REMOVED) == []
    assert _change_tuples(cell_changes) == [
        ("Data", "B2", ChangeType.VALUE_CHANGED),
        ("Data", "B3", ChangeType.VALUE_CHANGED),
    ]


# ------------------------------------------------------------- edge shapes


def test_blank_inserted_row_has_no_samples(tmp_path: Path):
    old_cells = {f"A{r}": r * 10 for r in range(2, 8)}
    new_cells = {f"A{r}": r * 10 for r in range(2, 5)}
    new_cells.update({f"A{r + 1}": r * 10 for r in range(5, 8)})  # rows 5..7 -> 6..8
    old = make_workbook(tmp_path / "old.xlsx", {"Data": old_cells})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": new_cells})

    structural, cell_changes = _diff(old, new)

    inserted = _row_changes(structural, StructuralChangeType.ROWS_INSERTED)
    assert len(inserted) == 1
    assert inserted[0].details == {"start_row": 5, "count": 1, "sample_cells": []}
    assert cell_changes == []


def test_cell_added_to_existing_blank_row_stays_a_cell_change(tmp_path: Path):
    """Filling a blank row does not shift anything: it must stay a per-cell
    addition, never a remove+insert pair."""
    base = {"A1": "x", "A2": 1, "A3": 2, "A5": 3, "A6": 4}  # row 4 blank
    new_cells = dict(base)
    new_cells["B4"] = 42
    old = make_workbook(tmp_path / "old.xlsx", {"Data": base})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": new_cells})

    structural, cell_changes = _diff(old, new)

    assert _row_changes(structural, StructuralChangeType.ROWS_INSERTED) == []
    assert _row_changes(structural, StructuralChangeType.ROWS_REMOVED) == []
    assert _change_tuples(cell_changes) == [("Data", "B4", ChangeType.VALUE_ADDED)]


def test_two_separate_runs_report_separately(tmp_path: Path):
    new_items = list(_BASE_ITEMS)
    new_items.insert(8, ("Late A", 71))  # will be row 10 after earlier inserts
    new_items.insert(8, ("Late B", 72))
    new_items.insert(2, ("Early", 70))  # row 4
    old = make_workbook(tmp_path / "old.xlsx", {"Data": _ledger(_BASE_ITEMS)})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": _ledger(new_items)})

    structural, cell_changes = _diff(old, new)

    inserted = _row_changes(structural, StructuralChangeType.ROWS_INSERTED)
    assert [(c.details["start_row"], c.details["count"]) for c in inserted] == [
        (4, 1),
        (11, 2),
    ]
    # Still only the grown total leaks through as a cell change.
    assert _change_tuples(cell_changes) == [("Data", "C15", ChangeType.FORMULA_CHANGED)]


def test_sample_previews_cap_at_five(tmp_path: Path):
    new_items = list(_BASE_ITEMS)
    for i in range(3):
        new_items.insert(4, (f"Block {i}", 900 + i))  # 3-row run, 3 cells each
    old = make_workbook(tmp_path / "old.xlsx", {"Data": _ledger(_BASE_ITEMS)})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": _ledger(new_items)})

    structural, _ = _diff(old, new)

    inserted = _row_changes(structural, StructuralChangeType.ROWS_INSERTED)
    assert len(inserted) == 1
    assert inserted[0].details["count"] == 3
    assert len(inserted[0].details["sample_cells"]) == 5


def test_alignment_applies_to_inferred_rename_pairs(tmp_path: Path):
    """D3 rename inference is untouched; the aligned diff then runs on the
    renamed pair and collapses the appended row."""
    cells: dict[str, Any] = {}
    for row in range(2, 8):
        cells[f"A{row}"] = row * 10
        cells[f"B{row}"] = f"=A{row}*2"
    new_cells = dict(cells)
    new_cells["A8"] = 999  # appended data row (rows 2..7 keep their formulas)
    old = make_workbook(tmp_path / "old.xlsx", {"Data": cells})
    new = make_workbook(tmp_path / "new.xlsx", {"Data2024": new_cells})

    structural, cell_changes = _diff(old, new)

    renames = [
        c for c in structural if c.change_type == StructuralChangeType.SHEET_RENAMED
    ]
    assert len(renames) == 1
    assert renames[0].details["inferred"] is True
    inserted = _row_changes(structural, StructuralChangeType.ROWS_INSERTED)
    assert len(inserted) == 1
    assert inserted[0].sheet_name == "Data2024"
    assert inserted[0].details["start_row"] == 8
    assert inserted[0].details["count"] == 1
    assert cell_changes == []


# ------------------------------------------------ acceptance 5: determinism


def test_diff_is_deterministic_within_process(tmp_path: Path):
    """Two independent runs over freshly parsed inventories produce identical
    output (the cross-PYTHONHASHSEED guarantee lives in the determinism
    integration suite)."""
    new_items = list(_BASE_ITEMS)
    new_items.insert(4, ("Item X", 999))
    old = make_workbook(tmp_path / "old.xlsx", {"Data": _ledger(_BASE_ITEMS)})
    new = make_workbook(tmp_path / "new.xlsx", {"Data": _ledger(new_items)})

    first_structural, first_changes = _diff(old, new)
    second_structural, second_changes = _diff(old, new)

    assert [c.model_dump() for c in first_structural] == [
        c.model_dump() for c in second_structural
    ]
    assert [c.model_dump() for c in first_changes] == [
        c.model_dump() for c in second_changes
    ]
