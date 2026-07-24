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
