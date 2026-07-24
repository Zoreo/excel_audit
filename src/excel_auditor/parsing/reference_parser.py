"""Parsing of A1-style cell and range references.

Handles: `A1`, `$A$1`, `A1:B2`, `A:C`, `1:3`, `Sheet1!A1`, `'My Sheet'!A1:B2`,
external forms such as `[1]Sheet1!A1` and `'[Book.xlsx]Data'!B2`.

Anything that does not look like an A1 reference (defined names, structured
table references) returns None and is left untouched by callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from openpyxl.utils import column_index_from_string

_CELL_RE = re.compile(r"^(?P<cabs>\$?)(?P<col>[A-Za-z]{1,3})(?P<rabs>\$?)(?P<row>\d{1,7})$")
_COL_RE = re.compile(r"^(?P<cabs>\$?)(?P<col>[A-Za-z]{1,3})$")
_ROW_RE = re.compile(r"^(?P<rabs>\$?)(?P<row>\d{1,7})$")
_EXTERNAL_RE = re.compile(r"\[(?P<ext>[^\]]*)\]")


@dataclass(frozen=True)
class CellRef:
    """One endpoint of a reference. row/column are None for whole-column/row refs."""

    row: int | None
    column: int | None
    row_absolute: bool = False
    column_absolute: bool = False


@dataclass(frozen=True)
class ParsedReference:
    raw: str
    sheet: str | None  # None means "same sheet as the formula"
    external: str | None  # external workbook marker, e.g. "1" or "Book.xlsx"
    start: CellRef
    end: CellRef | None

    @property
    def is_range(self) -> bool:
        return self.end is not None

    @property
    def is_external(self) -> bool:
        return self.external is not None


def _split_sheet_prefix(token: str) -> tuple[str | None, str]:
    """Split "'My Sheet'!A1" into ("My Sheet", "A1"). Handles '' escaping."""
    if token.startswith("'"):
        buf: list[str] = []
        i = 1
        n = len(token)
        closed = False
        while i < n:
            ch = token[i]
            if ch == "'":
                if i + 1 < n and token[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                closed = True
                break
            buf.append(ch)
            i += 1
        if not closed:
            return None, token
        rest = token[i + 1 :]
        if not rest.startswith("!"):
            return None, token
        return "".join(buf), rest[1:]
    if "!" in token:
        prefix, _, rest = token.partition("!")
        return prefix, rest
    return None, token


def _parse_endpoint(part: str) -> CellRef | None:
    m = _CELL_RE.match(part)
    if m:
        return CellRef(
            row=int(m.group("row")),
            column=column_index_from_string(m.group("col").upper()),
            row_absolute=m.group("rabs") == "$",
            column_absolute=m.group("cabs") == "$",
        )
    m = _COL_RE.match(part)
    if m:
        return CellRef(
            row=None,
            column=column_index_from_string(m.group("col").upper()),
            column_absolute=m.group("cabs") == "$",
        )
    m = _ROW_RE.match(part)
    if m:
        return CellRef(
            row=int(m.group("row")),
            column=None,
            row_absolute=m.group("rabs") == "$",
        )
    return None


def parse_reference(token: str) -> ParsedReference | None:
    token = token.strip()
    if not token:
        return None

    prefix, ref_part = _split_sheet_prefix(token)
    external: str | None = None
    sheet = prefix
    if prefix is not None:
        m = _EXTERNAL_RE.search(prefix)
        if m:
            external = m.group("ext")
            sheet = prefix[m.end() :] or None

    if ":" in ref_part:
        start_raw, _, end_raw = ref_part.partition(":")
        start = _parse_endpoint(start_raw)
        end = _parse_endpoint(end_raw)
        if start is None or end is None:
            return None
        # Endpoints must agree in kind (cell:cell, col:col, row:row).
        if (start.row is None) != (end.row is None):
            return None
        if (start.column is None) != (end.column is None):
            return None
        return ParsedReference(raw=token, sheet=sheet, external=external, start=start, end=end)

    start = _parse_endpoint(ref_part)
    # A bare single endpoint must be a full cell ref; "ABC" alone is a defined name.
    if start is None or start.row is None or start.column is None:
        return None
    return ParsedReference(raw=token, sheet=sheet, external=external, start=start, end=None)
