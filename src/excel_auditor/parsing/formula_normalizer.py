"""Formula normalization to relative (R1C1-style) form.

`=B2*C2` in D2 and `=B3*C3` in D3 both normalize to `RC[-2]*RC[-1]`, so copied
formulas can be compared structurally instead of textually. Absolute axes keep
their absolute row/column number, so `Assumptions!$B$2` normalizes identically
from every host cell.
"""

from __future__ import annotations

from .formula_tokenizer import (
    SUBTYPE_OPEN,
    SUBTYPE_RANGE,
    TYPE_FUNC,
    TYPE_OPERAND,
    TYPE_WSPACE,
    tokenize,
)
from .reference_parser import CellRef, ParsedReference, parse_reference


def _normalize_endpoint(ref: CellRef, base_row: int, base_column: int) -> str:
    row_part = ""
    if ref.row is not None:
        if ref.row_absolute:
            row_part = f"R{ref.row}"
        else:
            offset = ref.row - base_row
            row_part = "R" if offset == 0 else f"R[{offset}]"
    col_part = ""
    if ref.column is not None:
        if ref.column_absolute:
            col_part = f"C{ref.column}"
        else:
            offset = ref.column - base_column
            col_part = "C" if offset == 0 else f"C[{offset}]"
    return row_part + col_part


def normalize_reference(parsed: ParsedReference, *, base_row: int, base_column: int) -> str:
    parts: list[str] = []
    if parsed.external is not None:
        parts.append(f"[EXT:{parsed.external.upper()}]")
    if parsed.sheet:
        parts.append(parsed.sheet.upper() + "!")
    parts.append(_normalize_endpoint(parsed.start, base_row, base_column))
    if parsed.end is not None:
        parts.append(":" + _normalize_endpoint(parsed.end, base_row, base_column))
    return "".join(parts)


def normalize_formula(formula: str, *, row: int, column: int) -> str | None:
    """Normalize a formula relative to its host cell (1-based row/column).

    Returns None when the formula cannot be tokenized.
    """
    tokens = tokenize(formula)
    if tokens is None:
        return None
    out: list[str] = []
    for tok in tokens:
        if tok.type == TYPE_WSPACE:
            continue
        if tok.type == TYPE_OPERAND and tok.subtype == SUBTYPE_RANGE:
            parsed = parse_reference(tok.value)
            if parsed is not None:
                out.append(normalize_reference(parsed, base_row=row, base_column=column))
            else:
                # Defined name or structured ref: names are case-insensitive.
                out.append(tok.value.upper())
        elif tok.type == TYPE_FUNC and tok.subtype == SUBTYPE_OPEN:
            out.append(tok.value.upper())
        else:
            out.append(tok.value)
    return "".join(out)
