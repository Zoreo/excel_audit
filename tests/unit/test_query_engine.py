from datetime import date

from excel_auditor.models.query import (
    AggregateFunction,
    FilterOperator,
    PeriodComparison,
    QueryFilter,
    QueryOperation,
    ResultStatus,
    SpreadsheetQuery,
)
from excel_auditor.query_service import answer_query


def _query(**kwargs) -> SpreadsheetQuery:
    return SpreadsheetQuery(**kwargs)


def _year_filter(year: int) -> QueryFilter:
    return QueryFilter(column="__date__", operator=FilterOperator.YEAR_EQUALS, value=year)


def test_sum_with_year_filter_and_provenance(sales_bg):
    report = answer_query(
        sales_bg,
        _query(
            operation=QueryOperation.AGGREGATE,
            function=AggregateFunction.SUM,
            requested_metric="Оборот",
            filters=[_year_filter(2025)],
        ),
        exact_columns=True,
    )
    result = report.result
    assert result.status == ResultStatus.REVIEW_RECOMMENDED  # blanks excluded
    assert result.value == 628400
    assert result.formatted_value == "€628,400"
    p = result.provenance
    assert p.sheet == "Sales"
    assert p.value_column == "Оборот"
    assert p.date_column == "Дата"
    assert p.filters == ["year(Дата) = 2025"]
    assert p.rows_included == 7
    assert p.rows_excluded_blank == 2
    assert p.rows_excluded_total_rows == 1
    assert p.currency == "EUR"
    assert any("total/subtotal" in a for a in p.assumptions)


def test_subtotal_row_not_double_counted(sales_bg):
    report = answer_query(
        sales_bg,
        _query(function=AggregateFunction.SUM, requested_metric="Оборот"),
        exact_columns=True,
    )
    # all data rows, subtotal excluded: 400000 + 628400
    assert report.result.value == 1028400


def test_average_min_max_median(sales_bg_simple):
    def run(function):
        return answer_query(
            sales_bg_simple,
            _query(
                function=function,
                requested_metric="Оборот",
                filters=[_year_filter(2025)],
            ),
            exact_columns=True,
        ).result.value

    assert run(AggregateFunction.AVERAGE) == 125680
    assert run(AggregateFunction.MINIMUM) == 100000
    assert run(AggregateFunction.MAXIMUM) == 150000
    assert run(AggregateFunction.MEDIAN) == 128400


def test_distinct_count(sales_bg):
    report = answer_query(
        sales_bg,
        _query(function=AggregateFunction.DISTINCT_COUNT, requested_metric="Клиент"),
        exact_columns=True,
    )
    assert report.result.value == 5


def test_group_by_region(sales_bg):
    report = answer_query(
        sales_bg,
        _query(
            function=AggregateFunction.SUM,
            requested_metric="Оборот",
            group_by=["Регион"],
        ),
        exact_columns=True,
    )
    groups = {row.key["Регион"]: row.value for row in report.result.groups}
    assert groups["София"] == 628400
    assert groups["Пловдив"] == 250000
    assert groups["Варна"] == 150000


def test_group_by_month(sales_bg_simple):
    report = answer_query(
        sales_bg_simple,
        _query(
            function=AggregateFunction.SUM,
            requested_metric="Оборот",
            group_by=["month"],
            filters=[_year_filter(2025)],
        ),
        exact_columns=True,
    )
    groups = {row.key["Дата"]: row.value for row in report.result.groups}
    assert groups["2025-01"] == 100000
    assert groups["2025-05"] == 128400
    assert any("Grouped by month" in a for a in report.result.provenance.assumptions)


def test_period_comparison(sales_bg_simple):
    report = answer_query(
        sales_bg_simple,
        _query(
            operation=QueryOperation.COMPARE_PERIODS,
            function=AggregateFunction.SUM,
            requested_metric="Оборот",
            period_comparison=PeriodComparison(period_a=2024, period_b=2025),
        ),
        exact_columns=True,
    )
    comparison = report.result.comparison
    assert comparison["value_a"] == 400000
    assert comparison["value_b"] == 628400
    assert comparison["change"] == 228400
    assert comparison["pct_change"] == 57.1


def test_filter_greater_than_lists_rows(sales_bg_simple):
    report = answer_query(
        sales_bg_simple,
        _query(
            operation=QueryOperation.LIST_ROWS,
            filters=[
                QueryFilter(
                    column="Оборот",
                    operator=FilterOperator.GREATER_THAN,
                    value=125000,
                )
            ],
        ),
        exact_columns=True,
    )
    # 150000+130000 (2024) and 150000+130000+128400 (2025)
    assert report.result.value == 5
    assert len(report.result.rows) == 5


def test_next_deadline(contracts):
    report = answer_query(
        contracts,
        _query(operation=QueryOperation.NEXT_DEADLINE),
        exact_columns=True,
        reference_date=date(2026, 7, 24),
    )
    assert report.result.value == "2026-07-30"
    assert report.result.rows[0]["Договор"] == "Договор А"


def test_due_within(contracts):
    report = answer_query(
        contracts,
        _query(operation=QueryOperation.DUE_WITHIN, horizon_days=30),
        exact_columns=True,
        reference_date=date(2026, 7, 24),
    )
    assert report.result.value == 2  # 07-30 and 08-10


def test_overdue(contracts):
    report = answer_query(
        contracts,
        _query(operation=QueryOperation.OVERDUE),
        exact_columns=True,
        reference_date=date(2026, 7, 24),
    )
    assert report.result.value == 1
    assert report.result.rows[0]["Договор"] == "Договор Г"


def test_unknown_column_cannot_answer(sales_bg):
    report = answer_query(
        sales_bg,
        _query(function=AggregateFunction.SUM, requested_metric="Печалба"),
        exact_columns=True,
    )
    assert report.result.status == ResultStatus.CANNOT_ANSWER
    assert "schema" in (report.result.message or "")
