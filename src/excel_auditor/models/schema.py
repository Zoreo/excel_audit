"""Workbook schema models: detected tables, headers and column types."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .enums import SheetVisibility


class ColumnType(StrEnum):
    DATE = "date"
    NUMBER = "number"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"
    TEXT = "text"
    EMPTY = "empty"


class ColumnSchema(BaseModel):
    letter: str
    index: int  # 1-based worksheet column index
    name: str
    normalized_name: str
    type: ColumnType
    number_format: str | None = None
    currency: str | None = None  # ISO-ish code inferred from the number format
    likely_identifier: bool = False
    missing_count: int = 0
    distinct_count: int = 0
    sample_values: list[str] = Field(default_factory=list)


class TableSchema(BaseModel):
    sheet_name: str
    ref: str  # e.g. "A3:F387"
    header_rows: list[int] = Field(default_factory=list)
    data_start_row: int
    data_end_row: int
    row_count: int  # data rows, excluding header and detected total rows
    columns: list[ColumnSchema] = Field(default_factory=list)
    total_rows: list[int] = Field(default_factory=list)  # absolute row numbers
    notes: list[str] = Field(default_factory=list)

    def column(self, name: str) -> ColumnSchema | None:
        wanted = name.strip().casefold()
        for col in self.columns:
            if col.name.strip().casefold() == wanted or col.normalized_name == wanted:
                return col
        return None

    def display(self) -> str:
        return f"{self.sheet_name}!{self.ref}"


class SheetSchemaInfo(BaseModel):
    name: str
    visibility: SheetVisibility
    has_formulas: bool = False
    hidden_rows: int = 0
    hidden_columns: int = 0


class WorkbookSchema(BaseModel):
    workbook_id: str
    filename: str | None = None
    sheets: list[SheetSchemaInfo] = Field(default_factory=list)
    tables: list[TableSchema] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def tables_on(self, sheet_name: str) -> list[TableSchema]:
        wanted = sheet_name.strip().casefold()
        return [t for t in self.tables if t.sheet_name.casefold() == wanted]


class SchemaReport(BaseModel):
    engine_version: str
    generated_at: datetime
    workbook_schema: WorkbookSchema
    limitations: list[str] = Field(default_factory=list)
