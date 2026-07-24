"""Models describing the difference between two workbook versions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .dependency import DependencyImpact
from .enums import ChangeType, Confidence, Severity, StructuralChangeType
from .findings import Finding
from .reports import WorkbookSummary


class CellChange(BaseModel):
    sheet_name: str
    coordinate: str
    change_type: ChangeType
    old_value: Any = None
    new_value: Any = None
    old_formula: str | None = None
    new_formula: str | None = None
    normalized_old_formula: str | None = None
    normalized_new_formula: str | None = None
    severity: Severity = Severity.INFO
    confidence: Confidence = Confidence.HIGH
    explanation: str = ""
    downstream_impact: DependencyImpact | None = None


class StructuralChange(BaseModel):
    change_type: StructuralChangeType
    sheet_name: str | None = None
    description: str
    details: dict[str, Any] = Field(default_factory=dict)


class ReviewItem(BaseModel):
    """One reviewable issue: a cell change, the audit findings at the same
    location, or both, unified under a single reconciled severity/confidence.

    This is the primary list a reviewer works through - the raw cell_changes
    and findings lists remain available as supporting detail, with their
    severities reconciled to match the review item.
    """

    sheet_name: str | None = None
    coordinate: str | None = None
    severity: Severity
    confidence: Confidence
    title: str
    change: CellChange | None = None
    findings: list[Finding] = Field(default_factory=list)
    downstream_impact: DependencyImpact | None = None

    def display_location(self) -> str:
        if self.sheet_name and self.coordinate:
            return f"{self.sheet_name}!{self.coordinate}"
        return self.sheet_name or "workbook"


class ComparisonSummary(BaseModel):
    total_cell_changes: int = 0
    total_review_items: int = 0
    changes_by_type: dict[str, int] = Field(default_factory=dict)
    review_items_by_severity: dict[str, int] = Field(default_factory=dict)
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    affected_sheets: list[str] = Field(default_factory=list)
    high_impact_changes: int = 0
    structural_change_count: int = 0


class WorkbookComparison(BaseModel):
    """Full comparison report between an old and a new workbook version."""

    report_schema_version: str = "2"
    engine_version: str
    generated_at: datetime
    old_workbook: WorkbookSummary
    new_workbook: WorkbookSummary
    structural_changes: list[StructuralChange] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    cell_changes: list[CellChange] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    failed_rules: list[str] = Field(default_factory=list)
    summary: ComparisonSummary = Field(default_factory=ComparisonSummary)
    risk_level: str = "minimal"
    risk_drivers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
