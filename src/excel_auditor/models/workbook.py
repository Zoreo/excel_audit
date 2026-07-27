"""Typed representation of a parsed workbook (the internal inventory)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import SheetVisibility


class CellLocation(BaseModel):
    workbook_id: str
    sheet_name: str
    coordinate: str | None = None

    def display(self) -> str:
        if self.coordinate:
            return f"{self.sheet_name}!{self.coordinate}"
        return self.sheet_name


class CellRecord(BaseModel):
    """One populated cell: value, formula and enough style info to diff formatting."""

    coordinate: str
    row: int
    column: int
    data_type: str
    value: Any = None
    formula: str | None = None
    normalized_formula: str | None = None
    number_format: str | None = None
    style_signature: str | None = None

    @property
    def is_formula(self) -> bool:
        return self.formula is not None

    @property
    def is_numeric_constant(self) -> bool:
        return (
            self.formula is None
            and isinstance(self.value, (int, float))
            and not isinstance(self.value, bool)
        )


class NamedRange(BaseModel):
    name: str
    refers_to: str | None = None
    scope: str | None = None  # None = workbook scope, otherwise sheet name
    hidden: bool = False


class TableInfo(BaseModel):
    """An Excel `Table` object (ListObject) as recorded in the file.

    `header_row_count` / `totals_row_count` come from the Table XML and are
    exact — unlike the block heuristics, they are Excel's own declaration of
    which rows of `ref` are header/totals. `None` in the file is coerced to 0
    at inventory time; the defaults mirror Excel's (one header row, no totals
    row).
    """

    name: str
    ref: str
    sheet_name: str
    header_row_count: int = 1
    totals_row_count: int = 0


class SheetInventory(BaseModel):
    name: str
    index: int
    visibility: SheetVisibility = SheetVisibility.VISIBLE
    max_row: int = 0
    max_column: int = 0
    dimensions: str | None = None
    protected: bool = False
    merged_ranges: list[str] = Field(default_factory=list)
    hidden_rows: list[int] = Field(default_factory=list)
    hidden_columns: list[str] = Field(default_factory=list)
    tables: list[TableInfo] = Field(default_factory=list)
    cells: dict[str, CellRecord] = Field(default_factory=dict)

    @property
    def formula_cells(self) -> list[CellRecord]:
        return [c for c in self.cells.values() if c.is_formula]

    @property
    def formula_count(self) -> int:
        return sum(1 for c in self.cells.values() if c.is_formula)

    @property
    def constant_count(self) -> int:
        return sum(1 for c in self.cells.values() if not c.is_formula)


class WorkbookInventory(BaseModel):
    workbook_id: str
    filename: str | None = None
    file_size: int | None = None
    sheets: list[SheetInventory] = Field(default_factory=list)
    named_ranges: list[NamedRange] = Field(default_factory=list)
    external_links: list[str] = Field(default_factory=list)
    has_macros: bool = False
    has_data_connections: bool = False
    calculation_mode: str | None = None
    # Excel's fullPrecision calc property; False = "Set precision as displayed".
    # None means the file did not state it (and must not be treated as False).
    full_precision: bool | None = None
    workbook_protected: bool = False

    @property
    def sheet_names(self) -> list[str]:
        return [s.name for s in self.sheets]

    def sheet(self, name: str) -> SheetInventory | None:
        """Case-insensitive sheet lookup (Excel sheet names are case-insensitive)."""
        wanted = name.strip().upper()
        for s in self.sheets:
            if s.name.upper() == wanted:
                return s
        return None
