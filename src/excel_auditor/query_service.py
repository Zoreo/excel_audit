"""Application service for schema inspection and constrained queries.

Every workflow follows the same shape:

    validated SpreadsheetQuery
        -> schema detection
        -> column/table resolution (may require user confirmation)
        -> deterministic execution (pandas)
        -> QueryResult with full provenance

Ambiguity is never resolved silently: the service returns
status=needs_confirmation with the candidate list, and the caller re-invokes
with the user's choice(s) appended to `choices`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from . import __version__
from .analysis.dependency_graph import DependencyGraph, impact_for
from .analysis.query import ResolvedQuery, execute_query
from .analysis.resolution import (
    ColumnMatch,
    Resolution,
    concepts_of,
    normalize,
    resolve_date_column,
    resolve_exact_column,
    resolve_metric,
    resolve_value_column_by_type,
)
from .analysis.schema import detect_workbook_schema
from .analysis.workbook_inventory import inventory_from_path
from .config import Settings, get_settings
from .models.query import (
    AggregateFunction,
    ColumnCandidate,
    QueryAction,
    QueryFilter,
    QueryOperation,
    QueryProvenance,
    QueryReport,
    QueryResult,
    ResultStatus,
    SpreadsheetQuery,
)
from .models.schema import ColumnSchema, SchemaReport, WorkbookSchema

SCHEMA_LIMITATIONS = [
    "Header rows, tables and column types are detected heuristically.",
    "Merged or multi-row headers are approximated and noted per table.",
    "Blocks without a recognizable header row are not treated as tables.",
]

QUERY_LIMITATIONS = [
    "Numbers come from saved cell values; formula cells contribute the value "
    "Excel last saved.",
    "Rows that look like totals/subtotals are excluded to avoid double counting.",
    "Column matching may require confirmation; aliases are never treated as "
    "proof of equivalence.",
    "The intent parser only maps wording to supported operations; it never "
    "computes numbers.",
]

_DATE_PLACEHOLDER = "__date__"
_MONTH_WORDS = {"month", "months", "месец", "месеца", "месеци", "monthly"}


class _NeedsConfirmation(Exception):
    def __init__(self, kind: str, message: str, matches: list[ColumnMatch]):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.matches = matches


def _candidates(matches: list[ColumnMatch]) -> list[ColumnCandidate]:
    return [
        ColumnCandidate(
            sheet_name=m.table.sheet_name,
            table_ref=m.table.ref,
            column_name=m.column.name,
            column_type=m.column.type.value,
            reason=m.reason,
        )
        for m in matches
    ]


class _ChoiceCursor:
    """Consumes user choices (1-based) for successive ambiguities in order."""

    def __init__(self, choices: list[int] | None):
        self._choices = list(choices or [])

    def pick(self, kind: str, message: str, resolution: Resolution) -> ColumnMatch:
        if resolution.status == "resolved":
            return resolution.matches[0]
        if resolution.status == "ambiguous":
            if self._choices:
                index = self._choices.pop(0)
                if 1 <= index <= len(resolution.matches):
                    return resolution.matches[index - 1]
                raise _NeedsConfirmation(kind, message, resolution.matches)
            raise _NeedsConfirmation(kind, message, resolution.matches)
        raise LookupError(message)


def inspect_schema(
    path: Path | str, *, settings: Settings | None = None, filename: str | None = None
) -> SchemaReport:
    settings = settings or get_settings()
    inventory = inventory_from_path(Path(path), settings=settings, filename=filename)
    return SchemaReport(
        engine_version=__version__,
        generated_at=datetime.now(UTC),
        workbook_schema=detect_workbook_schema(inventory),
        limitations=SCHEMA_LIMITATIONS,
    )


def answer_query(
    path: Path | str,
    query: SpreadsheetQuery,
    *,
    question: str | None = None,
    exact_columns: bool = False,
    choices: list[int] | None = None,
    reference_date: date | None = None,
    settings: Settings | None = None,
    filename: str | None = None,
) -> QueryReport:
    """Resolve and execute a structured query against a workbook.

    exact_columns=True (structured CLI/API queries): column names must match
    exactly. False (free-text ask): concept-level resolution that surfaces
    gross/net, actual/forecast and multi-date ambiguity for confirmation.
    """
    settings = settings or get_settings()
    inventory = inventory_from_path(Path(path), settings=settings, filename=filename)
    schema = detect_workbook_schema(inventory)

    try:
        result = _answer(
            inventory, schema, query,
            exact_columns=exact_columns,
            cursor=_ChoiceCursor(choices),
            reference_date=reference_date,
        )
    except _NeedsConfirmation as pending:
        result = QueryResult(
            status=ResultStatus.NEEDS_CONFIRMATION,
            message=pending.message,
            candidates=_candidates(pending.matches),
            candidate_kind=pending.kind,
            provenance=QueryProvenance(workbook=inventory.filename),
        )
    except (LookupError, ValueError) as exc:
        result = QueryResult(
            status=ResultStatus.CANNOT_ANSWER,
            message=str(exc),
            provenance=QueryProvenance(workbook=inventory.filename),
        )

    return QueryReport(
        engine_version=__version__,
        generated_at=datetime.now(UTC),
        workbook=inventory.filename,
        question=question,
        query=query,
        result=result,
        limitations=QUERY_LIMITATIONS,
    )


# ------------------------------------------------------------------ internal


def _answer(
    inventory,
    schema: WorkbookSchema,
    query: SpreadsheetQuery,
    *,
    exact_columns: bool,
    cursor: _ChoiceCursor,
    reference_date: date | None,
) -> QueryResult:
    if query.action == QueryAction.INSPECT_WORKBOOK:
        return _inspect_result(schema)
    if query.action == QueryAction.TRACE_DEPENDENCIES:
        return _trace_result(inventory, query.cell_reference)
    if query.action != QueryAction.QUERY_TABLE:
        raise ValueError(
            f"Action '{query.action.value}' is handled by its dedicated command."
        )

    tables = schema.tables
    if query.source_sheet_hint:
        hinted = schema.tables_on(query.source_sheet_hint)
        if hinted:
            tables = hinted
    if not tables:
        raise LookupError("No tabular data with a recognizable header was detected.")

    assumptions: list[str] = []
    operation = query.operation or QueryOperation.AGGREGATE
    function = query.function

    # ---- value column ------------------------------------------------------
    needs_value = operation in (QueryOperation.AGGREGATE, QueryOperation.COMPARE_PERIODS) and (
        function != AggregateFunction.COUNT or query.requested_metric is not None
    )
    value_match: ColumnMatch | None = None
    if needs_value:
        target = query.requested_metric
        if target:
            resolution = (
                resolve_exact_column(target, tables)
                if exact_columns
                else resolve_metric(target, tables)
            )
            if resolution.status == "not_found" and not exact_columns:
                resolution = resolve_exact_column(target, tables)
        else:
            resolution = resolve_value_column_by_type(tables)
            if resolution.status == "resolved":
                assumptions.append(
                    f"Assumed value column '{resolution.matches[0].column.name}' "
                    "(only numeric column)."
                )
        if resolution.status == "not_found":
            raise LookupError(
                f"Could not find a column matching {target!r}. Run `schema` to see "
                "available columns."
            )
        value_match = cursor.pick(
            "value_column",
            _plural_message(target or "value", resolution.matches),
            resolution,
        )

    # ---- table -------------------------------------------------------------
    if value_match is not None:
        table = value_match.table
    elif len(tables) == 1:
        table = tables[0]
    else:
        table_matches = [
            ColumnMatch(t, t.columns[0], "table", f"{t.row_count} rows") for t in tables
        ]
        table = cursor.pick(
            "table",
            "Several candidate tables exist; which one should be used?",
            Resolution("ambiguous", table_matches),
        ).table

    # ---- date column -------------------------------------------------------
    date_needed = (
        operation in (QueryOperation.COMPARE_PERIODS, QueryOperation.NEXT_DEADLINE,
                      QueryOperation.DUE_WITHIN, QueryOperation.OVERDUE)
        or any(f.column == _DATE_PLACEHOLDER for f in query.filters)
        or any(normalize(g) in _MONTH_WORDS for g in query.group_by)
    )
    date_column: ColumnSchema | None = None
    if date_needed:
        resolution = resolve_date_column([table], hint=query.date_column_hint)
        if resolution.status == "ambiguous" and operation in (
            QueryOperation.NEXT_DEADLINE,
            QueryOperation.DUE_WITHIN,
            QueryOperation.OVERDUE,
        ):
            # Prefer due-date-like columns for deadline questions.
            due = [
                m for m in resolution.matches if "due_date" in concepts_of(m.column.name)
            ]
            if len(due) == 1:
                resolution = Resolution("resolved", due)
        if resolution.status == "not_found":
            raise LookupError("No date column was detected in the selected table.")
        date_match = cursor.pick(
            "date_column",
            "Several date columns exist; which one applies?",
            resolution,
        )
        date_column = date_match.column
        if resolution.status == "resolved" and not query.date_column_hint:
            assumptions.append(f"Using date column '{date_column.name}'.")

    # ---- filters -----------------------------------------------------------
    resolved_filters: list[tuple[ColumnSchema, QueryFilter]] = []
    for flt in query.filters:
        if flt.column == _DATE_PLACEHOLDER:
            if date_column is None:
                raise LookupError("A date filter was requested but no date column exists.")
            resolved_filters.append((date_column, flt))
            continue
        resolution = resolve_exact_column(flt.column, [table])
        if resolution.status == "not_found":
            resolution = resolve_metric(flt.column, [table])
        if resolution.status == "not_found":
            raise LookupError(f"Filter column {flt.column!r} was not found.")
        match = cursor.pick(
            "filter_column",
            _plural_message(flt.column, resolution.matches),
            resolution,
        )
        resolved_filters.append((match.column, flt))

    # ---- group by ----------------------------------------------------------
    group_columns: list[ColumnSchema] = []
    for dimension in query.group_by:
        if normalize(dimension) in _MONTH_WORDS:
            if date_column is None:
                resolution = resolve_date_column([table])
                if resolution.status == "not_found":
                    raise LookupError("Grouping by month needs a date column.")
                date_column = cursor.pick(
                    "date_column", "Several date columns exist; which one applies?", resolution
                ).column
            group_columns.append(date_column)
            assumptions.append(f"Grouped by month of '{date_column.name}'.")
            continue
        resolution = resolve_exact_column(dimension, [table])
        if resolution.status == "not_found":
            resolution = resolve_metric(dimension, [table])
        if resolution.status == "not_found":
            raise LookupError(f"Grouping column {dimension!r} was not found.")
        match = cursor.pick(
            "group_column", _plural_message(dimension, resolution.matches), resolution
        )
        group_columns.append(match.column)

    resolved = ResolvedQuery(
        operation=operation,
        table=table,
        function=function,
        value_column=value_match.column if value_match else None,
        date_column=date_column,
        group_by=group_columns,
        filters=resolved_filters,
        period_comparison=query.period_comparison,
        horizon_days=query.horizon_days,
        limit=query.limit,
        reference_date=reference_date,
        assumptions=assumptions,
    )
    return execute_query(inventory, resolved)


def _plural_message(target: str, matches: list[ColumnMatch]) -> str:
    options = "\n".join(
        f"{i}. {m.table.sheet_name} → {m.column.name} ({m.column.type.value})"
        for i, m in enumerate(matches, start=1)
    )
    return f"I found {len(matches)} possible matches for '{target}':\n{options}"


def _inspect_result(schema: WorkbookSchema) -> QueryResult:
    lines = []
    for sheet in schema.sheets:
        marker = "" if sheet.visibility.value == "visible" else f" [{sheet.visibility.value}]"
        lines.append(f"{sheet.name}{marker}")
    rows = [
        {
            "sheet": t.sheet_name,
            "table": t.ref,
            "rows": t.row_count,
            "columns": ", ".join(f"{c.name} ({c.type.value})" for c in t.columns),
        }
        for t in schema.tables
    ]
    return QueryResult(
        status=ResultStatus.VERIFIED,
        message="Sheets: " + "; ".join(lines),
        rows=rows,
        provenance=QueryProvenance(
            workbook=schema.filename,
            operation="inspect_workbook",
            rows_included=len(rows),
        ),
    )


def _trace_result(inventory, cell_reference: str | None) -> QueryResult:
    if not cell_reference or "!" not in cell_reference:
        raise ValueError("Dependency traces need a reference like 'Sheet!D7'.")
    sheet_part, _, coordinate = cell_reference.rpartition("!")
    sheet_name = sheet_part.strip().strip("'")
    sheet = inventory.sheet(sheet_name)
    if sheet is None:
        raise LookupError(f"Sheet {sheet_name!r} was not found.")
    coordinate = coordinate.replace("$", "").upper()
    graph = DependencyGraph.build(inventory)
    impact = impact_for(graph, inventory, (sheet.name, coordinate))
    message = (
        f"{sheet.name}!{coordinate} feeds {impact.direct_dependent_count} direct and "
        f"{impact.transitive_dependent_count} transitive dependent cell(s) across "
        f"{', '.join(impact.affected_sheets) or 'no other sheets'}."
    )
    if impact.touches_outputs:
        message += f" Reaches output cells: {'; '.join(impact.sample_output_cells[:3])}."
    return QueryResult(
        status=ResultStatus.VERIFIED,
        message=message,
        value=impact.transitive_dependent_count,
        rows=[{"direct_dependents": impact.sample_direct_dependents}],
        provenance=QueryProvenance(
            workbook=inventory.filename,
            sheet=sheet.name,
            operation="trace_dependencies",
        ),
    )
