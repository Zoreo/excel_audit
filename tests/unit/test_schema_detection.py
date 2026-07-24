from conftest import make_workbook
from excel_auditor.analysis.schema import detect_workbook_schema
from excel_auditor.analysis.workbook_inventory import inventory_from_path
from excel_auditor.models.schema import ColumnType


def _schema(path):
    return detect_workbook_schema(inventory_from_path(path))


def test_sales_schema_detection(sales_bg):
    schema = _schema(sales_bg)
    assert len(schema.tables) == 1
    table = schema.tables[0]
    assert table.sheet_name == "Sales"
    assert table.ref.startswith("A1:")
    assert table.header_rows == [1]
    assert table.row_count == 10  # subtotal row excluded

    by_name = {c.name: c for c in table.columns}
    assert by_name["Дата"].type == ColumnType.DATE
    assert by_name["Оборот"].type == ColumnType.CURRENCY
    assert by_name["Оборот"].currency == "EUR"
    assert by_name["Нетен оборот"].type == ColumnType.CURRENCY
    assert by_name["Платено"].type == ColumnType.BOOLEAN
    assert by_name["Регион"].type == ColumnType.CATEGORICAL
    assert by_name["Оборот"].missing_count == 2
    assert by_name["Оборот"].sample_values


def test_subtotal_row_detected(sales_bg):
    table = _schema(sales_bg).tables[0]
    assert table.total_rows == [12]  # header 1 + 10 data rows + subtotal on 12
    assert any("total" in note.lower() for note in table.notes)


def test_multiple_tables_on_one_sheet(tmp_path):
    cells = {
        "A1": "Продукт", "B1": "Цена",
        "A2": "Хляб", "B2": 2.5,
        "A3": "Мляко", "B3": 3.2,
        "A4": "Сирене", "B4": 12.0,
        # blank row 5 separates the blocks
        "A6": "Регион", "B6": "Оборот",
        "A7": "София", "B7": 1000,
        "A8": "Пловдив", "B8": 800,
        "A9": "Варна", "B9": 650,
    }
    schema = _schema(make_workbook(tmp_path / "two_tables.xlsx", {"Данни": cells}))
    assert len(schema.tables) == 2
    refs = {t.ref for t in schema.tables}
    assert refs == {"A1:B4", "A6:B9"}


def test_hidden_sheet_warning(tmp_path):
    path = make_workbook(
        tmp_path / "hidden.xlsx",
        {
            "Видим": {"A1": "Име", "B1": "Сума", "A2": "х", "B2": 1, "A3": "у", "B3": 2},
            "Скрит": {"A1": "Име", "B1": "Сума", "A2": "z", "B2": 3, "A3": "w", "B3": 4},
        },
        hidden_sheets=("Скрит",),
    )
    schema = _schema(path)
    assert any("Скрит" in w for w in schema.warnings)
    assert {t.sheet_name for t in schema.tables} == {"Видим", "Скрит"}


def test_title_row_above_header_is_ignored(tmp_path):
    cells = {
        "A1": "Годишен отчет",
        "A2": "Месец", "B2": "Сума",
        "A3": "Ян", "B3": 100,
        "A4": "Фев", "B4": 200,
        "A5": "Март", "B5": 300,
    }
    schema = _schema(make_workbook(tmp_path / "title.xlsx", {"Отчет": cells}))
    assert len(schema.tables) == 1
    table = schema.tables[0]
    assert table.header_rows == [2]
    assert any("Title row" in note for note in table.notes)
    assert {c.name for c in table.columns} == {"Месец", "Сума"}


def test_no_header_block_is_skipped(tmp_path):
    cells = {f"A{r}": r * 10 for r in range(1, 6)}  # numbers only, no header
    schema = _schema(make_workbook(tmp_path / "nohdr.xlsx", {"Данни": cells}))
    assert schema.tables == []


def test_schema_report_service(sales_bg):
    from excel_auditor.query_service import inspect_schema
    from excel_auditor.reporting.html_report import render_schema_html

    report = inspect_schema(sales_bg)
    html = render_schema_html(report)
    assert "Оборот" in html
    assert "currency" in html
    assert report.limitations
