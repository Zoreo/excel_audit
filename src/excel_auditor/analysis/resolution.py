"""Column-name normalization, multilingual aliases, and resolution.

Resolution hierarchy (per product spec):

    approved client mapping   (future - not in this milestone)
        -> exact normalized name match
        -> known multilingual aliases (concept vocabulary)
        -> schema / datatype compatibility
        -> LLM candidate ranking (future)
        -> user confirmation

Aliases are never treated as proof of equivalence: when several plausible
columns exist (gross vs net, actual vs forecast, several date fields), the
result is AMBIGUOUS and the caller must ask the user.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models.schema import ColumnSchema, ColumnType, TableSchema

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

# Standard Bulgarian -> Latin transliteration (streamlined ISO 9 / official).
_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a",
    "ь": "y", "ю": "yu", "я": "ya",
}


def normalize(name: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    lowered = (name or "").casefold().strip()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    return _SPACE_RE.sub(" ", no_punct).strip()


def transliterate(name: str) -> str:
    return "".join(_CYR_TO_LAT.get(ch, ch) for ch in name)


def normalized_forms(name: str) -> set[str]:
    base = normalize(name)
    forms = {base, transliterate(base)}
    return {f for f in forms if f}


# --------------------------------------------------------------- vocabulary

# Canonical concept vocabulary (EN + BG + common transliterations). Kept in
# code rather than YAML to avoid a config-loading dependency; the structure
# matches the documented YAML shape one-to-one.
VOCABULARY: dict[str, list[str]] = {
    "revenue": [
        "revenue", "rev", "turnover", "sales", "оборот", "оборота", "оборотът",
        "приходи", "приход", "приходите",
    ],
    "net_revenue": [
        "net revenue", "net sales", "net turnover", "нетен оборот",
        "нетния оборот", "нетният оборот", "чисти приходи", "нетни приходи",
    ],
    "expenses": [
        "expenses", "costs", "cost", "spend", "разходи", "разход", "разходите",
    ],
    "margin": ["margin", "gross margin", "марж", "маржа", "надценка"],
    "amount": ["amount", "value", "сума", "стойност"],
    "quantity": [
        "quantity", "qty", "units", "количество", "количеството", "бройки",
    ],
    "price": ["price", "unit price", "цена", "цената", "единична цена"],
    "date": [
        "date", "дата", "invoice date", "transaction date", "период", "period",
        "дата на фактура",
    ],
    "due_date": [
        "due date", "deadline", "падеж", "краен срок", "срок", "дата на плащане",
        "payment date",
    ],
    "customer": [
        "customer", "customers", "client", "clients", "клиент", "клиенти",
        "клиента", "клиентите", "контрагент", "купувач",
    ],
    "region": [
        "region", "regions", "area", "регион", "региона", "региони",
        "регионите", "район", "област",
    ],
    "product": [
        "product", "products", "item", "продукт", "продукти", "артикул", "стока",
    ],
    "invoice": [
        "invoice", "invoices", "фактура", "фактури", "фактурите",
        "invoice number", "номер на фактура",
    ],
    "paid": ["paid", "платено", "платена", "is paid"],
    "forecast": ["forecast", "прогноза", "план", "plan", "budget", "бюджет"],
    "actual": ["actual", "actuals", "факт", "отчет"],
    "identifier": ["id", "no", "number", "номер", "код", "code"],
}

# When a question mentions several concepts ("average invoice value"), prefer
# the most metric-like one; "amount" is generic and comes late deliberately.
METRIC_PRIORITY = [
    "net_revenue", "revenue", "expenses", "margin", "price", "quantity",
    "invoice", "amount", "customer", "product", "region", "paid",
]

# Concept families: a request for the base concept must surface refined
# variants as candidates instead of silently picking one.
CONCEPT_FAMILIES: dict[str, set[str]] = {
    "revenue": {"revenue", "net_revenue"},
    "net_revenue": {"net_revenue"},
    "date": {"date", "due_date"},
    "due_date": {"due_date"},
}

_ALIAS_TO_CONCEPT: dict[str, str] = {}
for _concept, _aliases in VOCABULARY.items():
    for _alias in _aliases:
        for _form in normalized_forms(_alias):
            # First writer wins; more specific concepts should list longer aliases.
            _ALIAS_TO_CONCEPT.setdefault(_form, _concept)


def concepts_of(name: str) -> set[str]:
    """All concepts whose aliases match the name exactly or as whole words."""
    found: set[str] = set()
    forms = normalized_forms(name)
    for form in forms:
        if form in _ALIAS_TO_CONCEPT:
            found.add(_ALIAS_TO_CONCEPT[form])
        words = set(form.split())
        for alias_form, concept in _ALIAS_TO_CONCEPT.items():
            alias_words = alias_form.split()
            if len(alias_words) == 1 and alias_form in words:
                found.add(concept)
            elif len(alias_words) > 1 and f" {alias_form} " in f" {form} ":
                found.add(concept)
    return found


def concepts_in_text(text: str) -> list[str]:
    """Concepts mentioned in free text, longest alias match first.

    When a longer alias subsumes a shorter one ("нетен оборот" contains
    "оборот"), only the more specific concept is kept.
    """
    norm = " " + normalize(text) + " "
    translit = " " + transliterate(normalize(text)) + " "
    matches: list[tuple[str, str]] = []  # (alias_form, concept)
    for alias_form, concept in _ALIAS_TO_CONCEPT.items():
        needle = f" {alias_form} "
        if needle in norm or needle in translit:
            matches.append((alias_form, concept))
    matches.sort(key=lambda m: len(m[0]), reverse=True)
    kept: list[tuple[str, str]] = []
    for alias_form, concept in matches:
        if any(f" {alias_form} " in f" {seen} " for seen, _ in kept):
            continue  # subsumed by a longer, more specific alias
        kept.append((alias_form, concept))
    ordered: list[str] = []
    for _, concept in kept:
        if concept not in ordered:
            ordered.append(concept)
    return ordered


# --------------------------------------------------------------- resolution


@dataclass(frozen=True)
class ColumnMatch:
    table: TableSchema
    column: ColumnSchema
    match_kind: str  # "exact" | "alias" | "type"
    reason: str = ""


@dataclass(frozen=True)
class Resolution:
    status: str  # "resolved" | "ambiguous" | "not_found"
    matches: list[ColumnMatch] = field(default_factory=list)

    @property
    def single(self) -> ColumnMatch | None:
        return self.matches[0] if self.status == "resolved" else None


_NUMERIC_TYPES = {ColumnType.NUMBER, ColumnType.CURRENCY, ColumnType.PERCENTAGE}


def _dedupe(matches: list[ColumnMatch]) -> list[ColumnMatch]:
    # Keyed on the PHYSICAL column (letter), not its header text: two distinct
    # columns sharing a header must stay separate matches so ambiguity is
    # surfaced instead of silently collapsing to one "resolved" column.
    seen: set[tuple[str, str, str]] = set()
    out: list[ColumnMatch] = []
    for m in matches:
        key = (m.table.sheet_name, m.table.ref, m.column.letter)
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def resolve_exact_column(name: str, tables: list[TableSchema]) -> Resolution:
    """Exact-name resolution for structured queries (--value-column Оборот)."""
    forms = normalized_forms(name)
    exact = [
        ColumnMatch(t, c, "exact", "exact name match")
        for t in tables
        for c in t.columns
        if normalized_forms(c.name) & forms
    ]
    exact = _dedupe(exact)
    if len(exact) == 1:
        return Resolution("resolved", exact)
    if len(exact) > 1:
        return Resolution("ambiguous", exact)
    # fall back to concept resolution
    return resolve_metric(name, tables)


def resolve_metric(text: str, tables: list[TableSchema]) -> Resolution:
    """Concept-level resolution for free-text metrics ("оборот", "revenue").

    Deliberately surfaces ALL family variants (gross vs net, actual vs
    forecast) as candidates so the user confirms instead of the tool guessing.
    """
    # concepts_in_text applies longest-alias subsumption, so an explicit
    # "нетен оборот" resolves to net_revenue only, while a bare "оборот"
    # keeps the whole revenue family in play.
    concepts = set(concepts_in_text(text)) or concepts_of(text)
    wanted: set[str] = set()
    for concept in concepts:
        wanted |= CONCEPT_FAMILIES.get(concept, {concept})

    matches: list[ColumnMatch] = []
    if wanted:
        for table in tables:
            for column in table.columns:
                overlap = concepts_of(column.name) & wanted
                if overlap and (
                    column.type in _NUMERIC_TYPES
                    or not any(c in {"revenue", "net_revenue", "expenses", "amount",
                                     "margin", "quantity", "price"} for c in overlap)
                ):
                    matches.append(
                        ColumnMatch(
                            table,
                            column,
                            "alias",
                            f"matches concept(s): {', '.join(sorted(overlap))}",
                        )
                    )
    matches = _dedupe(matches)
    if len(matches) == 1:
        return Resolution("resolved", matches)
    if len(matches) > 1:
        return Resolution("ambiguous", matches)
    return Resolution("not_found", [])


def resolve_value_column_by_type(tables: list[TableSchema]) -> Resolution:
    """Type-compatibility fallback: usable only when exactly one numeric
    column exists across candidate tables."""
    matches = [
        ColumnMatch(t, c, "type", f"only {c.type.value} column")
        for t in tables
        for c in t.columns
        if c.type in _NUMERIC_TYPES and not c.likely_identifier
    ]
    matches = _dedupe(matches)
    if len(matches) == 1:
        return Resolution("resolved", matches)
    if matches:
        return Resolution("ambiguous", matches)
    return Resolution("not_found", [])


def resolve_date_column(
    tables: list[TableSchema], *, hint: str | None = None
) -> Resolution:
    if hint:
        resolution = resolve_exact_column(hint, tables)
        if resolution.status != "not_found":
            return resolution
    matches = [
        ColumnMatch(t, c, "type", "date-typed column")
        for t in tables
        for c in t.columns
        if c.type == ColumnType.DATE
    ]
    matches = _dedupe(matches)
    if len(matches) == 1:
        return Resolution("resolved", matches)
    if matches:
        return Resolution("ambiguous", matches)
    return Resolution("not_found", [])
