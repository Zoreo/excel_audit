"""Rule-based intent parser (English + Bulgarian).

Deterministic keyword/regex mapping from user wording to a validated
SpreadsheetQuery. Deliberately conservative: anything it cannot map cleanly
raises UnsupportedQuestionError with the list of supported question types.
"""

from __future__ import annotations

import re

from ..analysis.resolution import METRIC_PRIORITY, concepts_in_text, normalize
from ..models.query import (
    AggregateFunction,
    FilterOperator,
    PeriodComparison,
    QueryAction,
    QueryFilter,
    QueryOperation,
    SpreadsheetQuery,
)
from ..models.schema import WorkbookSchema
from .interface import UnsupportedQuestionError

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_WITHIN_DAYS_RE = re.compile(r"(?:within|до|в рамките на)\s+(\d{1,3})\s+(?:days?|дни|дена)")
_NUMBER_RE = re.compile(r"(?<![\w.])(\d[\d\s.,]*)(?![\w])")
_CELL_REF_RE = re.compile(r"((?:'[^']+')|[\w.&-]+)!\$?[A-Za-z]{1,3}\$?\d{1,7}")

_REJECT_MARKERS = [
    "everything interesting", "всичко интересно",
    "why is", "why the", "защо",
    "forecast the", "predict", "прогнозирай", "предскажи",
    "fraud", "измама", "измами",
    "should i", "should we", "дали да", "струва ли си",
    "good investment", "добра инвестиция",
]

_SUPPORTED_HINT = (
    "Supported question types: workbook inspection, aggregations (sum, count, "
    "distinct count, average, min, max, median), filtered counts, grouped "
    "aggregations, period comparisons, deadline lookups, audits, comparisons "
    "and dependency traces."
)

_FUNCTION_KEYWORDS: list[tuple[AggregateFunction, list[str]]] = [
    (AggregateFunction.DISTINCT_COUNT, ["unique", "distinct", "уникални", "различни"]),
    (AggregateFunction.AVERAGE, [
        "average", "avg", "mean",
        "среден", "средна", "средно", "средният", "средната",
    ]),
    (AggregateFunction.MEDIAN, ["median", "медиана"]),
    (AggregateFunction.MINIMUM, [
        "minimum", "lowest", "smallest", "минимум", "минимал",
        "най нисък", "най ниска", "най ниско",
        "най малък", "най малка", "най малко",
    ]),
    (AggregateFunction.MAXIMUM, [
        "maximum", "highest", "largest", "biggest", "максимум", "максимал",
        "най висок", "най висока", "най високо",
        "най голям", "най голяма", "най голямо",
    ]),
    (AggregateFunction.SUM, [
        "total", "sum", "общ", "общо", "общият", "общия", "общата", "общите",
        "сума", "сумата", "сумарно",
    ]),
    (AggregateFunction.COUNT, [
        "how many", "count", "number of", "колко", "брой", "броят", "броя",
    ]),
]

_DEADLINE_KEYWORDS = [
    "due", "overdue", "deadline", "expire", "expires", "expiring",
    "краен срок", "крайни срокове", "изтича", "изтичат", "падеж", "просрочен", "просрочени", "срок",
]
_COMPARE_KEYWORDS = [
    "compare", "vs", "versus", "year over year", "спрямо", "сравни", "сравнение", "на годишна база",
]
_INSPECT_KEYWORDS = [
    "what sheets", "which sheets", "list sheets", "what columns", "which columns",
    "какви листове", "кои листове", "какви колони", "кои колони", "какви са колоните",
]
_AUDIT_KEYWORDS = ["audit", "одит", "одитирай", "провери за грешки"]
_TRACE_KEYWORDS = ["trace dependencies", "trace", "проследи зависимостите", "проследи"]
_GROUP_RE = re.compile(r"(?:\bby\b|\bпо\b)\s+([\wЀ-ӿ]{2,30})")
_LIST_KEYWORDS = [
    "show rows", "list rows", "show all rows",
    "покажи редовете", "покажи редове", "покажи всички редове",
]
_EXCEED_KEYWORDS = ["exceed", "exceeds", "over", "above", "more than", "над", "повече от"]
_OVERDUE_KEYWORDS = ["overdue", "просрочен", "просрочени", "просрочена"]


def _match_any(question: str, keywords: list[str]) -> bool:
    padded = f" {question} "
    return any(f" {normalize(kw)} " in padded for kw in keywords)


class RuleBasedIntentParser:
    """Maps EN/BG wording onto the structured query model. No LLM involved."""

    def parse(self, question: str, schema: WorkbookSchema) -> SpreadsheetQuery:
        raw = question.strip()
        if not raw:
            raise UnsupportedQuestionError("Empty question. " + _SUPPORTED_HINT)
        norm = normalize(raw)

        # Workbook-analysis actions first (they may contain reject-looking words).
        if _match_any(norm, _TRACE_KEYWORDS):
            cell = _CELL_REF_RE.search(raw)
            if cell:
                return SpreadsheetQuery(
                    action=QueryAction.TRACE_DEPENDENCIES, cell_reference=cell.group(0)
                )
        if _match_any(norm, _AUDIT_KEYWORDS) and "compare" not in norm:
            return SpreadsheetQuery(action=QueryAction.AUDIT_WORKBOOK)
        if _match_any(norm, _INSPECT_KEYWORDS) or ("hidden" in norm and "sheet" in norm):
            return SpreadsheetQuery(action=QueryAction.INSPECT_WORKBOOK)

        for marker in _REJECT_MARKERS:
            if normalize(marker) in norm:
                raise UnsupportedQuestionError(
                    f"This question is out of scope ('{marker.strip()}'). " + _SUPPORTED_HINT
                )

        concepts = [
            c for c in concepts_in_text(raw) if c not in ("date", "due_date", "identifier")
        ]
        metric = min(
            concepts,
            key=lambda c: METRIC_PRIORITY.index(c) if c in METRIC_PRIORITY else 99,
            default=None,
        )
        years = [int(y) for y in _YEAR_RE.findall(raw)]

        # Period comparison: two years + comparison wording.
        if len(years) >= 2 and _match_any(norm, _COMPARE_KEYWORDS):
            return SpreadsheetQuery(
                operation=QueryOperation.COMPARE_PERIODS,
                function=AggregateFunction.SUM,
                requested_metric=metric,
                period_comparison=PeriodComparison(period_a=years[0], period_b=years[1]),
            )

        # Deadlines.
        if _match_any(norm, _DEADLINE_KEYWORDS):
            if _match_any(norm, _OVERDUE_KEYWORDS):
                return SpreadsheetQuery(operation=QueryOperation.OVERDUE)
            within = _WITHIN_DAYS_RE.search(norm)
            if within:
                return SpreadsheetQuery(
                    operation=QueryOperation.DUE_WITHIN,
                    horizon_days=int(within.group(1)),
                )
            if "this week" in norm or "тази седмица" in norm:
                return SpreadsheetQuery(
                    operation=QueryOperation.DUE_WITHIN, horizon_days=7
                )
            if _match_any(norm, ["next", "следващ", "следващият", "следващия", "кога е"]):
                return SpreadsheetQuery(operation=QueryOperation.NEXT_DEADLINE)
            if _match_any(norm, ["how many", "колко", "count", "брой"]):
                within_default = 30
                return SpreadsheetQuery(
                    operation=QueryOperation.DUE_WITHIN, horizon_days=within_default
                )
            return SpreadsheetQuery(operation=QueryOperation.NEXT_DEADLINE)

        # List rows with a numeric threshold.
        if _match_any(norm, _LIST_KEYWORDS) or (
            "where" in norm and _match_any(norm, _EXCEED_KEYWORDS)
        ):
            threshold = None
            number_match = _NUMBER_RE.search(norm.replace(" ", ""))
            if number_match and _match_any(norm, _EXCEED_KEYWORDS):
                threshold = float(
                    number_match.group(1).replace(",", "").replace(" ", "")
                )
            query = SpreadsheetQuery(
                operation=QueryOperation.LIST_ROWS, requested_metric=metric
            )
            if threshold is not None and metric:
                query.filters.append(
                    QueryFilter(
                        column=metric,
                        operator=FilterOperator.GREATER_THAN,
                        value=threshold,
                    )
                )
            return query

        # Aggregations.
        function = None
        for candidate, keywords in _FUNCTION_KEYWORDS:
            if _match_any(norm, keywords):
                function = candidate
                break
        if function is None:
            if metric is not None:
                function = AggregateFunction.SUM  # "revenue by month" -> sum
            else:
                raise UnsupportedQuestionError(
                    "Could not map the question to a supported operation. "
                    + _SUPPORTED_HINT
                )

        # "how many customers" -> distinct count of that dimension.
        _entity_metrics = ("customer", "product", "region", "invoice")
        if function == AggregateFunction.COUNT and metric in _entity_metrics:
            function = AggregateFunction.DISTINCT_COUNT

        query = SpreadsheetQuery(
            operation=QueryOperation.AGGREGATE,
            function=function,
            requested_metric=metric,
        )
        if years and len(years) == 1:
            query.filters.append(
                QueryFilter(
                    column="__date__",
                    operator=FilterOperator.YEAR_EQUALS,
                    value=years[0],
                )
            )
        group = _GROUP_RE.search(norm)
        if group:
            dimension = group.group(1).strip()
            # trim trailing year fragments picked up by the loose regex
            dimension = _YEAR_RE.sub("", dimension).strip()
            if dimension:
                query.group_by = [dimension]
        return query
