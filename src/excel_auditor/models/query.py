"""Structured query models: strict typed intent, execution result, provenance.

The engineering rule: user wording is parsed into a SpreadsheetQuery, the
deterministic engine executes it, and every numerical result carries full
provenance. No number is produced outside this pipeline.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class QueryAction(StrEnum):
    INSPECT_WORKBOOK = "inspect_workbook"
    QUERY_TABLE = "query_table"
    AUDIT_WORKBOOK = "audit_workbook"
    COMPARE_WORKBOOKS = "compare_workbooks"
    TRACE_DEPENDENCIES = "trace_dependencies"


class QueryOperation(StrEnum):
    AGGREGATE = "aggregate"
    LIST_ROWS = "list_rows"
    COMPARE_PERIODS = "compare_periods"
    NEXT_DEADLINE = "next_deadline"
    DUE_WITHIN = "due_within"
    OVERDUE = "overdue"


class AggregateFunction(StrEnum):
    SUM = "sum"
    COUNT = "count"
    DISTINCT_COUNT = "distinct_count"
    AVERAGE = "average"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    MEDIAN = "median"


class FilterOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_OR_EQUAL = "less_or_equal"
    YEAR_EQUALS = "year_equals"
    BEFORE = "before"
    AFTER = "after"
    IS_BLANK = "is_blank"
    NOT_BLANK = "not_blank"


class QueryFilter(BaseModel):
    column: str
    operator: FilterOperator
    value: Any = None


class PeriodComparison(BaseModel):
    period_a: int
    period_b: int
    unit: str = "year"


class SpreadsheetQuery(BaseModel):
    """Validated structured intent. Anything that does not fit this model is
    rejected before execution."""

    action: QueryAction = QueryAction.QUERY_TABLE
    operation: QueryOperation | None = None
    function: AggregateFunction | None = None
    requested_metric: str | None = None
    requested_dimensions: list[str] = Field(default_factory=list)
    filters: list[QueryFilter] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    period_comparison: PeriodComparison | None = None
    source_sheet_hint: str | None = None
    date_column_hint: str | None = None
    horizon_days: int | None = None
    limit: int | None = None
    cell_reference: str | None = None  # for trace_dependencies
    requires_confirmation: bool = False


class ResultStatus(StrEnum):
    VERIFIED = "verified"
    REVIEW_RECOMMENDED = "review_recommended"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CANNOT_ANSWER = "cannot_answer_safely"


class ColumnCandidate(BaseModel):
    sheet_name: str
    table_ref: str
    column_name: str
    column_type: str
    reason: str = ""

    def display(self) -> str:
        return f"{self.sheet_name} → {self.column_name}"


class QueryProvenance(BaseModel):
    workbook: str | None = None
    sheet: str | None = None
    table_ref: str | None = None
    value_column: str | None = None
    date_column: str | None = None
    operation: str | None = None
    function: str | None = None
    filters: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    rows_total: int = 0
    rows_included: int = 0
    rows_excluded_blank: int = 0
    rows_excluded_total_rows: int = 0
    currency: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GroupRow(BaseModel):
    key: dict[str, Any]
    value: Any = None
    rows: int = 0


class QueryResult(BaseModel):
    status: ResultStatus
    message: str | None = None
    value: Any = None
    formatted_value: str | None = None
    groups: list[GroupRow] = Field(default_factory=list)
    comparison: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[ColumnCandidate] = Field(default_factory=list)
    candidate_kind: str | None = None  # what the candidates disambiguate
    provenance: QueryProvenance = Field(default_factory=QueryProvenance)


class QueryReport(BaseModel):
    engine_version: str
    generated_at: datetime
    workbook: str | None = None
    question: str | None = None
    query: SpreadsheetQuery
    result: QueryResult
    limitations: list[str] = Field(default_factory=list)
