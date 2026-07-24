from excel_auditor.parsing.reference_parser import parse_reference


def test_simple_cell():
    ref = parse_reference("B2")
    assert ref is not None
    assert ref.sheet is None
    assert ref.start.row == 2
    assert ref.start.column == 2
    assert not ref.start.row_absolute
    assert not ref.is_range


def test_absolute_and_mixed():
    ref = parse_reference("$A$1")
    assert ref is not None
    assert ref.start.row_absolute and ref.start.column_absolute
    mixed = parse_reference("A$1")
    assert mixed is not None
    assert mixed.start.row_absolute and not mixed.start.column_absolute


def test_range():
    ref = parse_reference("D2:D13")
    assert ref is not None and ref.is_range
    assert ref.start.row == 2 and ref.end is not None and ref.end.row == 13


def test_whole_column_and_row():
    col = parse_reference("A:C")
    assert col is not None and col.start.row is None and col.end.column == 3
    row = parse_reference("1:3")
    assert row is not None and row.start.column is None and row.end.row == 3


def test_sheet_prefix():
    ref = parse_reference("Assumptions!$B$2")
    assert ref is not None and ref.sheet == "Assumptions"


def test_quoted_sheet_prefix():
    ref = parse_reference("'Revenue Forecast'!D14")
    assert ref is not None and ref.sheet == "Revenue Forecast"
    assert ref.start.row == 14


def test_quoted_sheet_with_escaped_quote():
    ref = parse_reference("'It''s a sheet'!A1")
    assert ref is not None and ref.sheet == "It's a sheet"


def test_external_reference():
    ref = parse_reference("'[Benchmarks.xlsx]Data'!B2")
    assert ref is not None
    assert ref.is_external
    assert ref.external == "Benchmarks.xlsx"
    assert ref.sheet == "Data"


def test_external_index_form():
    ref = parse_reference("[1]Sheet1!A1")
    assert ref is not None and ref.is_external and ref.external == "1"


def test_defined_name_rejected():
    assert parse_reference("TaxRate") is None
    assert parse_reference("TRUE") is None


def test_mismatched_range_kinds_rejected():
    assert parse_reference("A1:B") is None
