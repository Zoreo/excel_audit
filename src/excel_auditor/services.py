"""Application services shared by the CLI and the API.

These are the only entry points callers should need:

    audit_workbook(path)              -> AuditReport
    compare_workbooks(old, new)       -> WorkbookComparison
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .analysis.dependency_graph import DependencyGraph, impact_for
from .analysis.pattern_detection import detect_pattern_anomalies
from .analysis.review import build_review_items
from .analysis.rules import AuditContext
from .analysis.rules.base import run_all_rules_with_failures
from .analysis.severity import assess_risk, classify_cell_change
from .analysis.workbook_diff import compare_inventories
from .analysis.workbook_inventory import inventory_from_path
from .config import Settings, get_settings
from .models import (
    AuditReport,
    ChangeType,
    ComparisonSummary,
    Severity,
    WorkbookComparison,
    summarize_workbook,
)
from .models.enums import SEVERITY_ORDER

logger = logging.getLogger(__name__)

LIMITATIONS = [
    "Formulas are analyzed structurally; the engine does not recalculate the workbook.",
    "Cached values are whatever Excel last saved; openpyxl-generated files may have none.",
    "VBA macros are detected but never executed or analyzed.",
    "External references are treated as untrusted text and never followed.",
    "Column insertions are not inferred; they surface as many shifted-formula changes. "
    "Row insertions/removals are inferred and reported as structural changes.",
    "Password-protected and corrupted workbooks cannot be analyzed.",
    "Shared-formula expansion depends on how the source application saved the file.",
]

def _failed_rule_notes(failed_rules: list[str]) -> tuple[str, str]:
    """(limitations entry, risk_drivers entry) describing crashed rules."""
    ids = ", ".join(failed_rules)
    limitation = (
        f"Rule(s) {ids} crashed and their checks were not applied; "
        "analysis coverage is incomplete."
    )
    driver = (
        f"{len(failed_rules)} analysis rule(s) failed to run; "
        "results may be incomplete."
    )
    return limitation, driver


# Change types that can propagate through the dependency graph.
_IMPACTFUL_CHANGES = {
    ChangeType.FORMULA_CHANGED,
    ChangeType.FORMULA_TO_CONSTANT,
    ChangeType.CONSTANT_TO_FORMULA,
    ChangeType.FORMULA_REMOVED,
    ChangeType.VALUE_CHANGED,
    ChangeType.VALUE_REMOVED,
}


def audit_workbook(
    path: Path | str,
    *,
    settings: Settings | None = None,
    filename: str | None = None,
    generated_at: datetime | None = None,
) -> AuditReport:
    settings = settings or get_settings()
    inventory = inventory_from_path(Path(path), settings=settings, filename=filename)
    graph = DependencyGraph.build(inventory, max_range_cells=settings.max_range_cells)
    anomalies = detect_pattern_anomalies(inventory)
    ctx = AuditContext(inventory=inventory, graph=graph, pattern_anomalies=anomalies)
    findings, failed_rules = run_all_rules_with_failures(ctx)

    by_severity: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity.value] = by_severity.get(finding.severity.value, 0) + 1

    risk_level, risk_drivers = assess_risk(
        (f.severity for f in findings), noun="finding"
    )
    limitations = list(LIMITATIONS)
    if failed_rules:
        limitation, driver = _failed_rule_notes(failed_rules)
        limitations.append(limitation)
        risk_drivers.append(driver)
    return AuditReport(
        engine_version=__version__,
        generated_at=generated_at or datetime.now(UTC),
        workbook=summarize_workbook(inventory),
        findings=findings,
        findings_by_severity=by_severity,
        failed_rules=failed_rules,
        risk_level=risk_level,
        risk_drivers=risk_drivers,
        limitations=limitations,
    )


def compare_workbooks(
    old_path: Path | str,
    new_path: Path | str,
    *,
    settings: Settings | None = None,
    old_filename: str | None = None,
    new_filename: str | None = None,
    generated_at: datetime | None = None,
) -> WorkbookComparison:
    settings = settings or get_settings()
    old_inventory = inventory_from_path(
        Path(old_path), settings=settings, workbook_id="old", filename=old_filename
    )
    new_inventory = inventory_from_path(
        Path(new_path), settings=settings, workbook_id="new", filename=new_filename
    )

    structural, cell_changes = compare_inventories(old_inventory, new_inventory)

    # Enrich changes with downstream impact from the NEW workbook's graph,
    # then re-classify severity with that impact taken into account.
    graph = DependencyGraph.build(new_inventory, max_range_cells=settings.max_range_cells)
    for change in cell_changes:
        if change.change_type not in _IMPACTFUL_CHANGES:
            continue
        impact = impact_for(graph, new_inventory, (change.sheet_name, change.coordinate))
        change.downstream_impact = impact
        normalized_equal = bool(
            change.normalized_old_formula is not None
            and change.normalized_old_formula == change.normalized_new_formula
        )
        change.severity, change.confidence = classify_cell_change(
            change.change_type, normalized_equal=normalized_equal, impact=impact
        )

    # Standalone risk audit of the new version.
    anomalies = detect_pattern_anomalies(new_inventory)
    ctx = AuditContext(inventory=new_inventory, graph=graph, pattern_anomalies=anomalies)
    findings, failed_rules = run_all_rules_with_failures(ctx)

    # Unify changes and findings into review items. This also reconciles each
    # CellChange's severity/confidence with the findings at the same location.
    review_items = build_review_items(cell_changes, findings)

    changes_by_type: dict[str, int] = {}
    for change in cell_changes:
        changes_by_type[change.change_type.value] = (
            changes_by_type.get(change.change_type.value, 0) + 1
        )
    items_by_severity: dict[str, int] = {}
    for item in review_items:
        items_by_severity[item.severity.value] = (
            items_by_severity.get(item.severity.value, 0) + 1
        )
    findings_by_severity: dict[str, int] = {}
    for finding in findings:
        findings_by_severity[finding.severity.value] = (
            findings_by_severity.get(finding.severity.value, 0) + 1
        )

    high_impact = sum(
        1
        for item in review_items
        if SEVERITY_ORDER[item.severity] >= SEVERITY_ORDER[Severity.HIGH]
        or (item.downstream_impact is not None and item.downstream_impact.touches_outputs)
    )

    risk_level, risk_drivers = assess_risk(
        (item.severity for item in review_items), noun="review item"
    )
    limitations = list(LIMITATIONS)
    if failed_rules:
        limitation, driver = _failed_rule_notes(failed_rules)
        limitations.append(limitation)
        risk_drivers.append(driver)

    return WorkbookComparison(
        engine_version=__version__,
        generated_at=generated_at or datetime.now(UTC),
        old_workbook=summarize_workbook(old_inventory),
        new_workbook=summarize_workbook(new_inventory),
        structural_changes=structural,
        review_items=review_items,
        cell_changes=cell_changes,
        findings=findings,
        failed_rules=failed_rules,
        summary=ComparisonSummary(
            total_cell_changes=len(cell_changes),
            total_review_items=len(review_items),
            changes_by_type=changes_by_type,
            review_items_by_severity=items_by_severity,
            findings_by_severity=findings_by_severity,
            affected_sheets=sorted({c.sheet_name for c in cell_changes}),
            high_impact_changes=high_impact,
            structural_change_count=len(structural),
        ),
        risk_level=risk_level,
        risk_drivers=risk_drivers,
        limitations=limitations,
    )
