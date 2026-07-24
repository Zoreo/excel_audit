"""Audit finding model shared by all rules."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import Confidence, Severity
from .workbook import CellLocation


class Finding(BaseModel):
    rule_id: str
    title: str
    description: str
    severity: Severity
    confidence: Confidence
    location: CellLocation | None = None
    related_locations: list[CellLocation] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggested_action: str = ""
