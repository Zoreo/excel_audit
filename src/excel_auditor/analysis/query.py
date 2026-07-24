"""Deterministic table query engine.

Executes a validated, fully-resolved query against one detected table using
pandas. Every result carries provenance (rows included/excluded, blanks,
filters, assumptions). No LLM is ever involved in computing a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from ..models import WorkbookInventory
from ..models.query import (
    AggregateFunction,
    FilterOperator,
    GroupRow,
    PeriodComparison,
    QueryFilter,
    QueryOperation,
    QueryProvenance,
    QueryResult,
    ResultStatus,
)
from ..models.schema import ColumnSchema, ColumnType, TableSchema

_LIST_ROW_CAP = 50


@dataclass
class ResolvedQuery:
    """A query whose table and columns are already concrete."""

    operation: QueryOperation
    table: TableSchema
    function: AggregateFunction | None = None
    value_column: ColumnSchema | None = None
    date_column: ColumnSchema | None = None
    group_by: list[ColumnSchema] | None = None
    filters: list[tuple[ColumnSchema, QueryFilter]] | None = None
    period_comparison: PeriodComparison | None = None
    horizon_days: int | None = None
    limit: int | None = None
    reference_date: date | None = None  # injected for deterministic tests
    assumptions: list[str] | None = None


def load_table_frame(
    inventory: WorkbookInventory, table: TableSchema
) -> tuple[pd.DataFrame, int, int]:
    """Build a DataFrame from the table's body rows.

    Returns (frame, rows_total_in_block, rows_excluded_as_totals).
    Formula cells contribute their cached value when the file has one.
    """
    sheet = inventory.sheet(table.sheet_name)
    if sheet is None:
        raise ValueError(f"Sheet {table.sheet_name!r} not found")

    body_rows = [
        r
        for r in range(table.data_start_row, table.data_end_row + 1)
        if r not in set(table.total_rows)
    ]
    data: dict[str, list[Any]] = {}
    for column in table.columns:
        values: list[Any] = []
        for row in body_rows:
            record = sheet.cells.get(f"{column.letter}{row}")
            values.append(record.value if record is not None else None)
        data[column.name] = values
    frame = pd.DataFrame(data)
    # Drop rows that are entirely empty (spacer noise inside the block).
    frame = frame.dropna(how="all").reset_index(drop=True)
    rows_total = table.data_end_row - table.data_start_row + 1
    return frame, rows_total, len(table.total_rows)


def _as_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _as_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _filter_description(column: ColumnSchema, flt: QueryFilter) -> str:
    if flt.operator == FilterOperator.YEAR_EQUALS:
        return f"year({column.name}) = {flt.value}"
    if flt.operator in (FilterOperator.IS_BLANK, FilterOperator.NOT_BLANK):
        return f"{column.name} {flt.operator.value.replace('_', ' ')}"
    return f"{column.name} {flt.operator.value.replace('_', ' ')} {flt.value}"


def _apply_filter(
    frame: pd.DataFrame, column: ColumnSchema, flt: QueryFilter, warnings: list[str]
) -> pd.DataFrame:
    series = frame[column.name]
    op = flt.operator
    if op == FilterOperator.IS_BLANK:
        return frame[series.isna()]
    if op == FilterOperator.NOT_BLANK:
        return frame[series.notna()]

    if op == FilterOperator.YEAR_EQUALS:
        dates = _as_datetime(series)
        bad = int(series.notna().sum() - dates.notna().sum())
        if bad:
            warnings.append(
                f"{bad} value(s) in '{column.name}' could not be read as dates and "
                "were excluded by the date filter."
            )
        return frame[dates.dt.year == int(flt.value)]
    if op in (FilterOperator.BEFORE, FilterOperator.AFTER):
        dates = _as_datetime(series)
        target = pd.to_datetime(str(flt.value))
        mask = dates < target if op == FilterOperator.BEFORE else dates > target
        return frame[mask]

    if op in (
        FilterOperator.GREATER_THAN,
        FilterOperator.LESS_THAN,
        FilterOperator.GREATER_OR_EQUAL,
        FilterOperator.LESS_OR_EQUAL,
    ):
        numbers = _as_number(series)
        target_num = float(flt.value)
        if op == FilterOperator.GREATER_THAN:
            return frame[numbers > target_num]
        if op == FilterOperator.LESS_THAN:
            return frame[numbers < target_num]
        if op == FilterOperator.GREATER_OR_EQUAL:
            return frame[numbers >= target_num]
        return frame[numbers <= target_num]

    # equals / not_equals / contains: case-insensitive for text
    def _norm(v: Any) -> Any:
        return v.casefold().strip() if isinstance(v, str) else v

    target_value = _norm(flt.value)
    normalized = series.map(_norm)
    if op == FilterOperator.EQUALS:
        if isinstance(target_value, str):
            return frame[normalized == target_value]
        return frame[_as_number(series) == float(flt.value)]
    if op == FilterOperator.NOT_EQUALS:
        if isinstance(target_value, str):
            return frame[normalized != target_value]
        return frame[_as_number(series) != float(flt.value)]
    if op == FilterOperator.CONTAINS:
        return frame[
            normalized.map(lambda v: isinstance(v, str) and str(target_value) in v)
        ]
    raise ValueError(f"Unsupported filter operator: {op}")


def _aggregate(series: pd.Series, function: AggregateFunction) -> tuple[Any, int]:
    """Returns (value, blank_count_excluded)."""
    if function == AggregateFunction.COUNT:
        return int(series.notna().sum()), 0
    if function == AggregateFunction.DISTINCT_COUNT:
        return int(series.dropna().nunique()), int(series.isna().sum())
    numbers = _as_number(series)
    blanks = int(len(series) - numbers.notna().sum())
    clean = numbers.dropna()
    if clean.empty:
        return None, blanks
    if function == AggregateFunction.SUM:
        return float(clean.sum()), blanks
    if function == AggregateFunction.AVERAGE:
        return float(clean.mean()), blanks
    if function == AggregateFunction.MINIMUM:
        return float(clean.min()), blanks
    if function == AggregateFunction.MAXIMUM:
        return float(clean.max()), blanks
    if function == AggregateFunction.MEDIAN:
        return float(clean.median()), blanks
    raise ValueError(f"Unsupported aggregate function: {function}")


def format_value(value: Any, currency: str | None, function: AggregateFunction | None) -> str:
    if value is None:
        return "n/a"
    if function in (AggregateFunction.COUNT, AggregateFunction.DISTINCT_COUNT):
        return f"{int(value):,}"
    if isinstance(value, float):
        text = f"{value:,.2f}"
        text = text.removesuffix(".00")
        symbol = {"EUR": "€", "USD": "$", "GBP": "£", "BGN": "лв "}.get(currency or "")
        return f"{symbol}{text}" if symbol else text
    return str(value)


def _group_key_series(frame: pd.DataFrame, column: ColumnSchema) -> pd.Series:
    if column.type == ColumnType.DATE:
        return _as_datetime(frame[column.name]).dt.strftime("%Y-%m")
    return frame[column.name].map(
        lambda v: v.strip() if isinstance(v, str) else v
    )


def execute_query(inventory: WorkbookInventory, resolved: ResolvedQuery) -> QueryResult:
    table = resolved.table
    frame, rows_total, totals_excluded = load_table_frame(inventory, table)
    warnings: list[str] = []
    assumptions: list[str] = list(resolved.assumptions or [])
    if totals_excluded:
        assumptions.append(
            f"{totals_excluded} total/subtotal row(s) excluded to avoid double counting."
        )

    filters = resolved.filters or []
    for column, flt in filters:
        frame = _apply_filter(frame, column, flt, warnings)

    provenance = QueryProvenance(
        workbook=inventory.filename,
        sheet=table.sheet_name,
        table_ref=table.ref,
        value_column=resolved.value_column.name if resolved.value_column else None,
        date_column=resolved.date_column.name if resolved.date_column else None,
        operation=resolved.operation.value,
        function=resolved.function.value if resolved.function else None,
        filters=[_filter_description(c, f) for c, f in filters],
        group_by=[c.name for c in (resolved.group_by or [])],
        rows_total=rows_total,
        rows_included=int(len(frame)),
        rows_excluded_total_rows=totals_excluded,
        currency=resolved.value_column.currency if resolved.value_column else None,
        assumptions=assumptions,
        warnings=warnings,
    )

    operation = resolved.operation
    if operation == QueryOperation.AGGREGATE:
        return _run_aggregate(frame, resolved, provenance)
    if operation == QueryOperation.LIST_ROWS:
        return _run_list_rows(frame, resolved, provenance)
    if operation == QueryOperation.COMPARE_PERIODS:
        return _run_compare_periods(frame, resolved, provenance)
    if operation in (
        QueryOperation.NEXT_DEADLINE,
        QueryOperation.DUE_WITHIN,
        QueryOperation.OVERDUE,
    ):
        return _run_deadlines(frame, resolved, provenance)
    raise ValueError(f"Unsupported operation: {operation}")


def _finish(provenance: QueryProvenance, **kwargs: Any) -> QueryResult:
    status = (
        ResultStatus.REVIEW_RECOMMENDED
        if provenance.warnings
        else ResultStatus.VERIFIED
    )
    return QueryResult(status=status, provenance=provenance, **kwargs)


def _run_aggregate(
    frame: pd.DataFrame, resolved: ResolvedQuery, provenance: QueryProvenance
) -> QueryResult:
    function = resolved.function or AggregateFunction.SUM
    if resolved.value_column is None:
        # A bare COUNT over rows needs no value column.
        if function == AggregateFunction.COUNT:
            provenance.rows_included = int(len(frame))
            return _finish(provenance, value=int(len(frame)), formatted_value=f"{len(frame):,}")
        raise ValueError("Aggregate queries need a value column")

    series = frame[resolved.value_column.name]

    if resolved.group_by:
        keys = {c.name: _group_key_series(frame, c) for c in resolved.group_by}
        grouped_frame = frame.assign(**keys)
        grouped = grouped_frame.groupby(
            [c.name for c in resolved.group_by], dropna=False
        )
        rows: list[GroupRow] = []
        blanks_total = 0
        for key, part in grouped:
            key_tuple = key if isinstance(key, tuple) else (key,)
            value, blanks = _aggregate(part[resolved.value_column.name], function)
            blanks_total += blanks
            rows.append(
                GroupRow(
                    key={
                        c.name: (None if pd.isna(k) else k)
                        for c, k in zip(resolved.group_by, key_tuple, strict=True)
                    },
                    value=value,
                    rows=int(len(part)),
                )
            )
        rows.sort(key=lambda r: str(sorted(r.key.items())))
        provenance.rows_excluded_blank = blanks_total
        if blanks_total:
            provenance.warnings.append(
                f"{blanks_total} blank value(s) excluded from the aggregation."
            )
        return _finish(provenance, groups=rows)

    value, blanks = _aggregate(series, function)
    provenance.rows_excluded_blank = blanks
    if blanks:
        provenance.warnings.append(f"{blanks} blank value(s) excluded.")
    formatted = format_value(value, provenance.currency, function)
    return _finish(provenance, value=value, formatted_value=formatted)


def _run_list_rows(
    frame: pd.DataFrame, resolved: ResolvedQuery, provenance: QueryProvenance
) -> QueryResult:
    limit = min(resolved.limit or _LIST_ROW_CAP, _LIST_ROW_CAP)
    if len(frame) > limit:
        provenance.warnings.append(
            f"Showing the first {limit} of {len(frame)} matching rows."
        )
    records = frame.head(limit).to_dict(orient="records")
    clean = [
        {k: (None if pd.isna(v) else _plain(v)) for k, v in row.items()}
        for row in records
    ]
    return _finish(
        provenance,
        rows=clean,
        value=int(len(frame)),
        formatted_value=f"{len(frame):,} row(s)",
    )


def _plain(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _run_compare_periods(
    frame: pd.DataFrame, resolved: ResolvedQuery, provenance: QueryProvenance
) -> QueryResult:
    if resolved.date_column is None or resolved.value_column is None:
        raise ValueError("Period comparison needs a date column and a value column")
    comparison = resolved.period_comparison
    if comparison is None:
        raise ValueError("Period comparison parameters missing")
    function = resolved.function or AggregateFunction.SUM

    dates = _as_datetime(frame[resolved.date_column.name])
    blanks_total = 0
    values: dict[int, Any] = {}
    for period in (comparison.period_a, comparison.period_b):
        subset = frame[dates.dt.year == period]
        value, blanks = _aggregate(subset[resolved.value_column.name], function)
        blanks_total += blanks
        values[period] = value

    a = values[comparison.period_a]
    b = values[comparison.period_b]
    change = None
    pct_change = None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        change = b - a
        pct_change = (change / a * 100.0) if a else None
    provenance.rows_excluded_blank = blanks_total
    if blanks_total:
        provenance.warnings.append(f"{blanks_total} blank value(s) excluded.")
    details = {
        "period_a": comparison.period_a,
        "period_b": comparison.period_b,
        "value_a": a,
        "value_b": b,
        "change": change,
        "pct_change": round(pct_change, 2) if pct_change is not None else None,
        "function": function.value,
    }
    formatted = (
        f"{comparison.period_a}: {format_value(a, provenance.currency, function)} → "
        f"{comparison.period_b}: {format_value(b, provenance.currency, function)}"
        + (f" ({pct_change:+.1f}%)" if pct_change is not None else "")
    )
    return _finish(provenance, comparison=details, formatted_value=formatted)


def _run_deadlines(
    frame: pd.DataFrame, resolved: ResolvedQuery, provenance: QueryProvenance
) -> QueryResult:
    if resolved.date_column is None:
        raise ValueError("Deadline queries need a date column")
    reference = pd.to_datetime(resolved.reference_date or date.today())
    provenance.assumptions.append(f"Reference date: {reference.date().isoformat()}.")
    dates = _as_datetime(frame[resolved.date_column.name])

    if resolved.operation == QueryOperation.NEXT_DEADLINE:
        upcoming = frame[dates >= reference]
        upcoming_dates = dates[dates >= reference]
        if upcoming.empty:
            provenance.warnings.append("No dates on or after the reference date.")
            return _finish(provenance, value=None, formatted_value="none upcoming")
        next_date = upcoming_dates.min()
        row = upcoming[upcoming_dates == next_date].head(1).to_dict(orient="records")
        clean_row = [
            {k: (None if pd.isna(v) else _plain(v)) for k, v in r.items()} for r in row
        ]
        return _finish(
            provenance,
            value=next_date.date().isoformat(),
            formatted_value=next_date.date().isoformat(),
            rows=clean_row,
        )

    if resolved.operation == QueryOperation.OVERDUE:
        overdue = frame[dates < reference]
        records = overdue.head(_LIST_ROW_CAP).to_dict(orient="records")
        clean_overdue = [
            {k: (None if pd.isna(v) else _plain(v)) for k, v in row.items()}
            for row in records
        ]
        return _finish(
            provenance,
            value=int(len(overdue)),
            formatted_value=f"{len(overdue):,} overdue row(s)",
            rows=clean_overdue,
        )

    horizon = resolved.horizon_days or 30
    provenance.assumptions.append(f"Horizon: {horizon} day(s).")
    end = reference + pd.Timedelta(days=horizon)
    mask = (dates >= reference) & (dates <= end)
    matching = frame[mask]
    records = matching.head(_LIST_ROW_CAP).to_dict(orient="records")
    clean = [
        {k: (None if pd.isna(v) else _plain(v)) for k, v in row.items()}
        for row in records
    ]
    return _finish(
        provenance,
        value=int(len(matching)),
        formatted_value=f"{len(matching):,} row(s) due within {horizon} days",
        rows=clean,
    )
