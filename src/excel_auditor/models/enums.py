"""Shared enumerations."""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    """Potential business impact of a finding or change."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_ORDER: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class Confidence(StrEnum):
    """Likelihood that a finding is genuinely anomalous (not just present)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


CONFIDENCE_ORDER: dict[Confidence, int] = {
    Confidence.LOW: 0,
    Confidence.MEDIUM: 1,
    Confidence.HIGH: 2,
}


class SheetVisibility(StrEnum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    VERY_HIDDEN = "veryHidden"


class ChangeType(StrEnum):
    """Category of a single-cell difference between two workbook versions."""

    FORMULA_CHANGED = "formula_changed"
    VALUE_CHANGED = "value_changed"
    FORMULA_TO_CONSTANT = "formula_to_constant"
    CONSTANT_TO_FORMULA = "constant_to_formula"
    FORMULA_ADDED = "formula_added"
    FORMULA_REMOVED = "formula_removed"
    VALUE_ADDED = "value_added"
    VALUE_REMOVED = "value_removed"
    FORMATTING_ONLY = "formatting_only"


class StructuralChangeType(StrEnum):
    """Workbook-level (non-cell) differences between two versions."""

    SHEET_ADDED = "sheet_added"
    SHEET_REMOVED = "sheet_removed"
    SHEET_RENAMED = "sheet_renamed"
    SHEETS_REORDERED = "sheets_reordered"
    SHEET_VISIBILITY_CHANGED = "sheet_visibility_changed"
    NAMED_RANGE_ADDED = "named_range_added"
    NAMED_RANGE_REMOVED = "named_range_removed"
    NAMED_RANGE_CHANGED = "named_range_changed"
    EXTERNAL_LINK_ADDED = "external_link_added"
    EXTERNAL_LINK_REMOVED = "external_link_removed"
    MERGED_RANGES_CHANGED = "merged_ranges_changed"
    HIDDEN_ROWS_CHANGED = "hidden_rows_changed"
    HIDDEN_COLUMNS_CHANGED = "hidden_columns_changed"
    MACROS_CHANGED = "macros_changed"
