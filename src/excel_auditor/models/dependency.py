"""Dependency impact summary attached to changed or flagged cells."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DependencyImpact(BaseModel):
    direct_dependent_count: int = 0
    transitive_dependent_count: int = 0
    affected_sheets: list[str] = Field(default_factory=list)
    touches_outputs: bool = False
    sample_output_cells: list[str] = Field(default_factory=list)
    sample_direct_dependents: list[str] = Field(default_factory=list)
    is_circular: bool = False
    # Interim EXCEL-003 honesty marker. True when at least one formula in the
    # workbook used a defined-name or structured-table token the dependency
    # graph could not resolve into cell edges. While True, the dependent
    # counts above are lower bounds and may be understated for ANY cell —
    # without resolving names we cannot rule out that the queried cell is the
    # target of one, so the bound is workbook-level. A workbook whose formulas
    # contain no such tokens never carries the marker. Per-cell tightening
    # arrives with full named-range/table resolution (T4b).
    has_unresolved_names: bool = False
