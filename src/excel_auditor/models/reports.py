"""Report envelope models (what the API/CLI actually emit).

Reports carry *summaries* of workbooks, not the full cell inventory - the
inventory is an internal analysis structure and can be large.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import SheetVisibility
from .findings import Finding
from .workbook import NamedRange, SheetInventory, WorkbookInventory


class SheetSummary(BaseModel):
    name: str
    visibility: SheetVisibility
    max_row: int
    max_column: int
    formula_cells: int
    constant_cells: int
    hidden_rows: int
    hidden_columns: int
    merged_ranges: int
    protected: bool


class WorkbookSummary(BaseModel):
    workbook_id: str
    filename: str | None = None
    file_size: int | None = None
    sheets: list[SheetSummary] = Field(default_factory=list)
    named_ranges: list[NamedRange] = Field(default_factory=list)
    external_links: list[str] = Field(default_factory=list)
    has_macros: bool = False
    has_data_connections: bool = False
    calculation_mode: str | None = None
    workbook_protected: bool = False

    @property
    def total_formula_cells(self) -> int:
        return sum(s.formula_cells for s in self.sheets)


def summarize_sheet(sheet: SheetInventory) -> SheetSummary:
    return SheetSummary(
        name=sheet.name,
        visibility=sheet.visibility,
        max_row=sheet.max_row,
        max_column=sheet.max_column,
        formula_cells=sheet.formula_count,
        constant_cells=sheet.constant_count,
        hidden_rows=len(sheet.hidden_rows),
        hidden_columns=len(sheet.hidden_columns),
        merged_ranges=len(sheet.merged_ranges),
        protected=sheet.protected,
    )


def summarize_workbook(inventory: WorkbookInventory) -> WorkbookSummary:
    return WorkbookSummary(
        workbook_id=inventory.workbook_id,
        filename=inventory.filename,
        file_size=inventory.file_size,
        sheets=[summarize_sheet(s) for s in inventory.sheets],
        named_ranges=inventory.named_ranges,
        external_links=inventory.external_links,
        has_macros=inventory.has_macros,
        has_data_connections=inventory.has_data_connections,
        calculation_mode=inventory.calculation_mode,
        workbook_protected=inventory.workbook_protected,
    )


class AuditReport(BaseModel):
    """Standalone risk audit of a single workbook."""

    engine_version: str
    generated_at: datetime
    workbook: WorkbookSummary
    findings: list[Finding] = Field(default_factory=list)
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    risk_level: str = "minimal"
    risk_drivers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
