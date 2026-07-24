from pathlib import Path

from conftest import make_workbook
from excel_auditor.analysis.pattern_detection import detect_pattern_anomalies
from excel_auditor.analysis.workbook_inventory import inventory_from_path


def _detect(tmp_path: Path, cells: dict) -> list:
    path = make_workbook(tmp_path / "wb.xlsx", {"Data": cells})
    inventory = inventory_from_path(path)
    return detect_pattern_anomalies(inventory)


def test_hardcoded_value_in_column_pattern(tmp_path: Path):
    cells = {
        "B10": 1, "C10": 2, "D10": "=B10*C10",
        "B11": 1, "C11": 2, "D11": "=B11*C11",
        "B12": 1, "C12": 2, "D12": "=B12*C12",
        "B13": 1, "C13": 2, "D13": 1250,
        "B14": 1, "C14": 2, "D14": "=B14*C14",
    }
    anomalies = _detect(tmp_path, cells)
    hits = [a for a in anomalies if a.coordinate == "D13"]
    assert len(hits) == 1
    assert hits[0].kind == "overwritten_constant"
    assert hits[0].actual_value == 1250


def test_inconsistent_formula_with_shift_detection(tmp_path: Path):
    cells = {
        "A1": 1, "A2": 2, "A3": 3, "A4": 4, "A5": 5, "A6": 6, "A7": 7,
        "B2": "=A2*2",
        "B3": "=A3*2",
        "B4": "=A4*2",
        "B5": "=A4*2",  # wrong row: references A4 instead of A5
        "B6": "=A6*2",
        "B7": "=A7*2",
    }
    anomalies = _detect(tmp_path, cells)
    hits = [a for a in anomalies if a.coordinate == "B5"]
    assert len(hits) == 1
    assert hits[0].kind == "inconsistent_formula"
    assert hits[0].shifted_by is not None


def test_missing_formula_in_block(tmp_path: Path):
    cells = {
        "A1": 1, "A2": 2, "A3": 3, "A4": 4, "A5": 5,
        "B1": "=A1+1",
        "B2": "=A2+1",
        # B3 intentionally blank
        "B4": "=A4+1",
        "B5": "=A5+1",
    }
    anomalies = _detect(tmp_path, cells)
    hits = [a for a in anomalies if a.coordinate == "B3"]
    assert len(hits) == 1
    assert hits[0].kind == "missing_formula"


def test_row_orientation_pattern(tmp_path: Path):
    cells = {
        "B1": 1, "C1": 2, "D1": 3, "E1": 4, "F1": 5,
        "B2": "=B1*2", "C2": "=C1*2", "D2": 999, "E2": "=E1*2", "F2": "=F1*2",
    }
    anomalies = _detect(tmp_path, cells)
    hits = [a for a in anomalies if a.coordinate == "D2"]
    assert len(hits) == 1
    assert hits[0].orientation == "row"


def test_no_false_positive_on_distinct_formulas(tmp_path: Path):
    # A column of structurally different formulas (like a P&L) must not flag.
    cells = {
        "B2": "=C2*2",
        "B3": "=B2-C3",
        "B4": "=B3*0.4",
        "B5": "=B4-B3",
        "B6": "=MAX(0,B5)",
    }
    assert _detect(tmp_path, cells) == []


def test_demo_v2_detects_planted_anomalies(new_inventory):
    anomalies = detect_pattern_anomalies(new_inventory)
    by_key = {(a.sheet_name, a.coordinate): a for a in anomalies}
    overwritten = by_key.get(("Revenue Forecast", "D7"))
    assert overwritten is not None and overwritten.kind == "overwritten_constant"
    wrong_row = by_key.get(("Cash Flow", "B9"))
    assert wrong_row is not None and wrong_row.kind == "inconsistent_formula"
    assert wrong_row.shifted_by is not None


def test_demo_v1_is_clean(old_inventory):
    assert detect_pattern_anomalies(old_inventory) == []
