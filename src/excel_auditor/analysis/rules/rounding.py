"""Cent-level rounding drift.

EA-RND-001: displayed component figures that don't add up to the displayed
total (Excel stores full precision but displays rounded values; SUM works on
stored values, so the printed column can be off by a display unit).
EA-RND-002: the workbook-wide "Set precision as displayed" option, which
permanently destroys stored precision on save.

Display rounding matches Excel: ties away from zero (decimal.ROUND_HALF_UP),
never float round() (banker's rounding — wrong for display).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from openpyxl.utils import get_column_letter

from ...models import CellRecord, Confidence, Finding, Severity, SheetInventory
from ...parsing.formula_tokenizer import function_names, reference_tokens
from ...parsing.reference_parser import parse_reference
from .base import AuditContext, Rule, register

_TOTAL_FUNCTIONS = {"SUM", "SUBTOTAL"}
_MIN_COMPONENTS = 3  # D16: fewer populated components is not a "total"
_MAX_RESIDUE_CELLS = 10
_MAX_FINDINGS = 25
# Longest contiguous run walked when inferring the range of a hardcoded total.
_MAX_COMPONENT_SCAN = 200
_RESIDUE_EPSILON = Decimal("1e-9")
# Ordered so that '[$€-2]'-style formats match the euro before the '$'.
_CURRENCY_SYMBOLS = (("€", "EUR"), ("лв", "BGN"), ("£", "GBP"), ("$", "USD"))
# Any of these letters (unquoted) marks a date/time or scientific format.
_NON_FIXED_LETTERS = frozenset("ymdhse")


def _split_sections(number_format: str) -> list[str]:
    """Split a format on ';' outside quoted literals."""
    sections: list[str] = []
    buf: list[str] = []
    in_quotes = False
    for ch in number_format:
        if ch == '"':
            in_quotes = not in_quotes
        if ch == ";" and not in_quotes:
            sections.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    sections.append("".join(buf))
    return sections


def _strip_non_numeric(section: str) -> str:
    """Drop quoted literals, [..] blocks and escaped/padded characters."""
    out: list[str] = []
    i = 0
    n = len(section)
    while i < n:
        ch = section[i]
        if ch == '"':
            closing = section.find('"', i + 1)
            i = n if closing < 0 else closing + 1
        elif ch == "[":
            closing = section.find("]", i + 1)
            i = n if closing < 0 else closing + 1
        elif ch in "\\_*":
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _display_decimals(number_format: str | None) -> int | None:
    """Fixed decimal places a format displays (D15), or None.

    None means the cell does not participate: General, text, date, percent,
    scientific, and variable-decimals ('0.0#') formats all return None.
    """
    if not number_format:
        return None
    bare = _strip_non_numeric(_split_sections(number_format)[0])
    lowered = bare.casefold()
    if "general" in lowered or "@" in bare or "%" in bare:
        return None
    if _NON_FIXED_LETTERS & set(lowered):
        return None
    if "0" not in bare and "#" not in bare:
        return None
    _, sep, tail = bare.partition(".")
    if not sep:
        return 0
    decimals = 0
    for ch in tail:
        if ch == "0":
            decimals += 1
        elif ch in "#?":
            return None  # variable decimal places — not a fixed display
        else:
            break
    return decimals


def _currency_code(number_format: str | None) -> str | None:
    if not number_format:
        return None
    for symbol, code in _CURRENCY_SYMBOLS:
        if symbol in number_format:
            return code
    return None


def _numeric_value(record: CellRecord) -> float | None:
    """Stored numeric value: constants and cached formula values alike."""
    value = record.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _round_display(value: float, decimals: int) -> Decimal:
    """Excel display rounding: ties away from zero. str() keeps the shortest
    float repr, so Decimal sees 31.005 and not 31.004999...."""
    quantum = Decimal(1).scaleb(-decimals)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


@register
class RoundingDriftRule(Rule):
    rule_id = "EA-RND-001"
    title = "Displayed figures don't add up"
    description = (
        "The rounded values a reader sees do not sum to the rounded total - "
        "sub-display precision in the components drifts into the printed figures."
    )

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        cache: dict[str, int | None] = {}
        for sheet in ctx.inventory.sheets:
            for record in sheet.formula_cells:
                components, range_label = self._formula_components(sheet, record)
                if components is None:
                    continue
                finding = self._evaluate(ctx, sheet, record, components, range_label, cache)
                if finding is not None:
                    findings.append(finding)
                    if len(findings) >= _MAX_FINDINGS:
                        return findings
            for record in sheet.cells.values():
                if not record.is_numeric_constant:
                    continue
                if self._decimals(record, cache) is None:
                    continue
                for components in (
                    _contiguous_run(sheet, record, d_row=-1, d_col=0),
                    _contiguous_run(sheet, record, d_row=0, d_col=-1),
                ):
                    if len(components) < _MIN_COMPONENTS:
                        continue
                    label = f"{components[0].coordinate}:{components[-1].coordinate}"
                    finding = self._evaluate(ctx, sheet, record, components, label, cache)
                    if finding is not None:
                        findings.append(finding)
                        break
                if len(findings) >= _MAX_FINDINGS:
                    return findings
        return findings

    @staticmethod
    def _decimals(record: CellRecord, cache: dict[str, int | None]) -> int | None:
        fmt = record.number_format or ""
        if fmt not in cache:
            cache[fmt] = _display_decimals(fmt)
        return cache[fmt]

    @staticmethod
    def _formula_components(
        sheet: SheetInventory, record: CellRecord
    ) -> tuple[list[CellRecord] | None, str]:
        """Populated cells of a single-area same-sheet SUM/SUBTOTAL range."""
        assert record.formula is not None
        if not function_names(record.formula) & _TOTAL_FUNCTIONS:
            return None, ""
        tokens = reference_tokens(record.formula)
        if len(tokens) != 1:  # conservative: exactly one referenced area
            return None, ""
        parsed = parse_reference(tokens[0].value)
        if (
            parsed is None
            or parsed.is_external
            or parsed.end is None
            or parsed.start.row is None
            or parsed.start.column is None
            or parsed.end.row is None
            or parsed.end.column is None
        ):
            return None, ""
        if parsed.sheet is not None and parsed.sheet.upper() != sheet.name.upper():
            return None, ""
        row_lo, row_hi = sorted((parsed.start.row, parsed.end.row))
        col_lo, col_hi = sorted((parsed.start.column, parsed.end.column))
        components = [
            cell
            for cell in sheet.cells.values()
            if cell.coordinate != record.coordinate
            and row_lo <= cell.row <= row_hi
            and col_lo <= cell.column <= col_hi
        ]
        return components, tokens[0].value

    def _evaluate(
        self,
        ctx: AuditContext,
        sheet: SheetInventory,
        total: CellRecord,
        components: list[CellRecord],
        range_label: str,
        cache: dict[str, int | None],
    ) -> Finding | None:
        total_decimals = self._decimals(total, cache)
        if total_decimals is None:
            return None
        total_value = _numeric_value(total)
        if total_value is None:  # e.g. formula without a cached value
            return None
        if len(components) < _MIN_COMPONENTS:
            return None

        values: list[tuple[CellRecord, float, int]] = []
        for cell in components:
            value = _numeric_value(cell)
            decimals = self._decimals(cell, cache)
            if value is None or decimals is None:  # conservative: skip the range
                return None
            values.append((cell, value, decimals))

        unit = Decimal(1).scaleb(-total_decimals)
        stored_sum = sum((Decimal(str(v)) for _, v, _ in values), Decimal(0))
        # Only display artifacts: the stored figures must actually agree,
        # otherwise this is not a total (or not a *rounding* problem).
        if abs(stored_sum - Decimal(str(total_value))) >= unit:
            return None

        displayed_sum = sum(
            (_round_display(v, d) for _, v, d in values), Decimal(0)
        )
        displayed_total = _round_display(total_value, total_decimals)
        drift = displayed_sum - displayed_total
        if abs(drift) < unit:
            return None

        residue_cells = []
        for cell, value, decimals in values:
            displayed = _round_display(value, decimals)
            if abs(Decimal(str(value)) - displayed) > _RESIDUE_EPSILON:
                residue_cells.append(
                    {"cell": cell.coordinate, "stored": value, "displayed": str(displayed)}
                )
            if len(residue_cells) >= _MAX_RESIDUE_CELLS:
                break

        evidence: dict[str, object] = {
            "range": range_label,
            "component_count": len(values),
            "displayed_components_sum": str(displayed_sum),
            "displayed_total": str(displayed_total),
            "drift": str(drift),
            "residue_cells": residue_cells,
        }
        currency = _currency_code(total.number_format)
        if currency is not None:
            evidence["currency"] = currency

        return Finding(
            rule_id=self.rule_id,
            title=self.title,
            description=(
                f"'{sheet.name}'!{total.coordinate} displays as {displayed_total}, "
                f"but the displayed components in {range_label} add up to "
                f"{displayed_sum} (drift {drift} = displayed components − "
                "displayed total)."
            ),
            severity=Severity.MEDIUM,
            confidence=Confidence.HIGH,
            location=ctx.location(sheet.name, total.coordinate),
            related_locations=[
                ctx.location(sheet.name, str(res["cell"])) for res in residue_cells
            ],
            evidence=evidence,
            suggested_action=(
                "Apply a consistent ROUND() policy on the components or document "
                "the adjustment."
            ),
        )


def _contiguous_run(
    sheet: SheetInventory, record: CellRecord, *, d_row: int, d_col: int
) -> list[CellRecord]:
    """Contiguous numeric cells walking up/left from a hardcoded total."""
    run: list[CellRecord] = []
    row, column = record.row + d_row, record.column + d_col
    while row >= 1 and column >= 1 and len(run) < _MAX_COMPONENT_SCAN:
        cell = sheet.cells.get(f"{get_column_letter(column)}{row}")
        if cell is None or _numeric_value(cell) is None:
            break
        run.append(cell)
        row += d_row
        column += d_col
    run.reverse()  # top-to-bottom / left-to-right, matching reading order
    return run


@register
class PrecisionAsDisplayedRule(Rule):
    rule_id = "EA-RND-002"
    title = "Precision as displayed is enabled"
    description = (
        "The workbook has Excel's 'Set precision as displayed' option on: stored "
        "values are permanently truncated to their displayed precision on save."
    )

    def run(self, ctx: AuditContext) -> list[Finding]:
        # Only an explicit fullPrecision="0" counts; absent (None) stays silent.
        if ctx.inventory.full_precision is not False:
            return []
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                description=(
                    "Workbook calculation property fullPrecision=\"0\" ('Set "
                    "precision as displayed'): every save irreversibly rounds "
                    "stored values to what the number formats display."
                ),
                severity=Severity.MEDIUM,
                confidence=Confidence.HIGH,
                evidence={"full_precision": False},
                suggested_action=(
                    "Disable 'Set precision as displayed' and use explicit ROUND() "
                    "where rounded arithmetic is intended."
                ),
            )
        ]
