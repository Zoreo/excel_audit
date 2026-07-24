import shutil
import zipfile
from pathlib import Path

import pytest

from excel_auditor.analysis.workbook_inventory import inventory_from_path
from excel_auditor.errors import WorkbookValidationError
from excel_auditor.models import SheetVisibility
from excel_auditor.parsing.workbook_loader import validate_container


def test_rejects_non_zip(tmp_path: Path):
    fake = tmp_path / "fake.xlsx"
    fake.write_text("this is not a workbook")
    with pytest.raises(WorkbookValidationError):
        validate_container(fake)


def test_rejects_missing_file(tmp_path: Path):
    with pytest.raises(WorkbookValidationError):
        validate_container(tmp_path / "nope.xlsx")


def test_rejects_zip_without_workbook_parts(tmp_path: Path):
    path = tmp_path / "notexcel.xlsx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hello.txt", "hi")
    with pytest.raises(WorkbookValidationError):
        validate_container(path)


def test_inventory_of_demo_v1(old_inventory):
    assert old_inventory.sheet_names == [
        "Assumptions",
        "Revenue Forecast",
        "P&L",
        "Cash Flow",
        "Summary",
    ]
    rf = old_inventory.sheet("Revenue Forecast")
    assert rf is not None
    assert rf.cells["D2"].formula == "=B2*C2"
    assert rf.cells["D2"].normalized_formula == "RC[-2]*RC[-1]"
    # named range captured
    assert any(n.name == "TaxRate" for n in old_inventory.named_ranges)
    # merged cell captured
    summary = old_inventory.sheet("Summary")
    assert summary is not None and "A1:B1" in summary.merged_ranges
    # hidden row/column with data captured
    assumptions = old_inventory.sheet("Assumptions")
    assert assumptions is not None
    assert 9 in assumptions.hidden_rows
    assert "E" in assumptions.hidden_columns
    assert not old_inventory.has_macros


def test_hidden_sheet_detected(new_inventory):
    adjustments = new_inventory.sheet("Adjustments")
    assert adjustments is not None
    assert adjustments.visibility == SheetVisibility.HIDDEN


def test_macro_detection_via_zip(tmp_path: Path, demo_paths):
    """Copy v1 and inject a fake vbaProject.bin -> has_macros must flip."""
    v1, _ = demo_paths
    xlsm = tmp_path / "with_macros.xlsm"
    shutil.copy(v1, xlsm)
    with zipfile.ZipFile(xlsm, "a") as zf:
        zf.writestr("xl/vbaProject.bin", b"\x00fake\x00")
    inventory = inventory_from_path(xlsm)
    assert inventory.has_macros
