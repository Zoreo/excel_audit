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
    # EXCEL-003 honesty marker. Defined names and structured table references
    # are resolved into real graph edges; this is True only when at least one
    # formula in the workbook used a token that GENUINELY could not be
    # resolved (unknown name, #REF!/formula-valued name, unsupported table
    # item specifier). While True, the dependent counts above are lower bounds
    # and may be understated for ANY cell — without resolving that token we
    # cannot rule out that the queried cell is its target, so the bound is
    # workbook-level. A workbook whose name tokens all resolve (or are
    # understood constants) never carries the marker.
    has_unresolved_names: bool = False
