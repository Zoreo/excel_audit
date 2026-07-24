"""Unify cell changes and audit findings into review items.

A single underlying problem (e.g. a formula overwritten by a constant) used to
surface twice - once as a cell change and once as a rule finding - and the two
could disagree on severity. Here they are merged into one ReviewItem per
location with a reconciled severity/confidence, which is also written back to
the CellChange so every representation in the report agrees.
"""

from __future__ import annotations

from collections import defaultdict

from ..models import (
    CONFIDENCE_ORDER,
    SEVERITY_ORDER,
    CellChange,
    ChangeType,
    Finding,
    ReviewItem,
)

_CHANGE_TITLES: dict[ChangeType, str] = {
    ChangeType.FORMULA_CHANGED: "Formula logic changed",
    ChangeType.VALUE_CHANGED: "Input value changed",
    ChangeType.FORMULA_TO_CONSTANT: "Formula replaced by a hardcoded value",
    ChangeType.CONSTANT_TO_FORMULA: "Hardcoded value replaced by a formula",
    ChangeType.FORMULA_ADDED: "Formula added",
    ChangeType.FORMULA_REMOVED: "Formula removed",
    ChangeType.VALUE_ADDED: "Value added",
    ChangeType.VALUE_REMOVED: "Value removed",
    ChangeType.FORMATTING_ONLY: "Formatting changed",
}


def _max_severity(candidates):
    return max(candidates, key=lambda s: SEVERITY_ORDER[s])


def _max_confidence(candidates):
    return max(candidates, key=lambda c: CONFIDENCE_ORDER[c])


def build_review_items(
    cell_changes: list[CellChange], findings: list[Finding]
) -> list[ReviewItem]:
    """Merge changes and findings into one deduplicated, reconciled list.

    Side effect (by design): each CellChange's severity/confidence is raised
    to its review item's reconciled values, so `cell_changes` never disagrees
    with `review_items`.
    """
    located: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    unlocated: list[Finding] = []
    for finding in findings:
        if finding.location and finding.location.coordinate:
            located[(finding.location.sheet_name, finding.location.coordinate)].append(finding)
        else:
            unlocated.append(finding)

    items: list[ReviewItem] = []

    for change in cell_changes:
        if change.change_type == ChangeType.FORMATTING_ONLY:
            continue  # reported in their own collapsed section, never review items
        related = located.pop((change.sheet_name, change.coordinate), [])
        severity = _max_severity([change.severity, *(f.severity for f in related)])
        confidence = _max_confidence([change.confidence, *(f.confidence for f in related)])
        # Reconcile the raw change with the unified item (fix for
        # "diff severity disagrees with audit findings").
        change.severity = severity
        change.confidence = confidence
        title = related[0].title if related else _CHANGE_TITLES[change.change_type]
        items.append(
            ReviewItem(
                sheet_name=change.sheet_name,
                coordinate=change.coordinate,
                severity=severity,
                confidence=confidence,
                title=title,
                change=change,
                findings=related,
                downstream_impact=change.downstream_impact,
            )
        )

    # Findings on cells that did not change (pre-existing risks in the new version).
    for (sheet_name, coordinate), group in located.items():
        items.append(
            ReviewItem(
                sheet_name=sheet_name,
                coordinate=coordinate,
                severity=_max_severity([f.severity for f in group]),
                confidence=_max_confidence([f.confidence for f in group]),
                title=group[0].title,
                findings=group,
            )
        )

    # Sheet- and workbook-level findings.
    for finding in unlocated:
        items.append(
            ReviewItem(
                sheet_name=finding.location.sheet_name if finding.location else None,
                coordinate=None,
                severity=finding.severity,
                confidence=finding.confidence,
                title=finding.title,
                findings=[finding],
            )
        )

    items.sort(
        key=lambda i: (
            -SEVERITY_ORDER[i.severity],
            -CONFIDENCE_ORDER[i.confidence],
            i.sheet_name or "",
            i.coordinate or "",
        )
    )
    return items
