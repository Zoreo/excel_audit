"""Rule interface and registry.

Each rule is independently testable: it receives an AuditContext (inventory +
dependency graph + pattern anomalies) and returns findings. Rules never raise
on odd content - a rule that cannot evaluate simply returns no findings.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field

from ...models import CellLocation, Finding, Severity, WorkbookInventory
from ...models.enums import CONFIDENCE_ORDER, SEVERITY_ORDER
from ..dependency_graph import DependencyGraph
from ..pattern_detection import PatternAnomaly

logger = logging.getLogger(__name__)

# When one rule fires on this many cells (or more) of the same sheet at
# medium-or-lower severity, the findings collapse into a single grouped
# finding so the report stays readable. High/critical stay per-cell.
GROUP_THRESHOLD = 4


@dataclass
class AuditContext:
    inventory: WorkbookInventory
    graph: DependencyGraph
    pattern_anomalies: list[PatternAnomaly] = field(default_factory=list)

    def location(self, sheet_name: str, coordinate: str | None = None) -> CellLocation:
        return CellLocation(
            workbook_id=self.inventory.workbook_id,
            sheet_name=sheet_name,
            coordinate=coordinate,
        )


class Rule(ABC):
    rule_id: str = ""
    title: str = ""
    description: str = ""

    @abstractmethod
    def run(self, ctx: AuditContext) -> list[Finding]: ...


ALL_RULES: list[type[Rule]] = []


def register(rule_cls: type[Rule]) -> type[Rule]:
    ALL_RULES.append(rule_cls)
    return rule_cls


def _group_repeated(findings: list[Finding]) -> list[Finding]:
    """Collapse repeated medium-or-lower cell findings per (rule, sheet)."""
    groupable: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    out: list[Finding] = []
    for finding in findings:
        if (
            SEVERITY_ORDER[finding.severity] <= SEVERITY_ORDER[Severity.MEDIUM]
            and finding.location is not None
            and finding.location.coordinate
        ):
            groupable[(finding.rule_id, finding.location.sheet_name)].append(finding)
        else:
            out.append(finding)

    for (rule_id, sheet_name), group in groupable.items():
        if len(group) < GROUP_THRESHOLD:
            out.extend(group)
            continue
        first = group[0]
        assert first.location is not None
        cells = [f.location.coordinate for f in group if f.location]
        out.append(
            Finding(
                rule_id=rule_id,
                title=f"{first.title} — {len(group)} cells",
                description=(
                    f"{len(group)} cells on '{sheet_name}' share this finding. "
                    f"Example: {first.description}"
                ),
                severity=max((f.severity for f in group), key=lambda s: SEVERITY_ORDER[s]),
                confidence=max(
                    (f.confidence for f in group), key=lambda c: CONFIDENCE_ORDER[c]
                ),
                location=CellLocation(
                    workbook_id=first.location.workbook_id, sheet_name=sheet_name
                ),
                related_locations=[f.location for f in group[:20] if f.location],
                evidence={"count": len(group), "cells": cells[:30]},
                suggested_action=first.suggested_action,
            )
        )
    return out


def run_all_rules(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    for rule_cls in ALL_RULES:
        rule = rule_cls()
        try:
            findings.extend(rule.run(ctx))
        except Exception:  # a broken rule must never sink the whole audit
            logger.exception("Rule %s failed", rule_cls.rule_id)
    findings = _group_repeated(findings)
    findings.sort(key=lambda f: SEVERITY_ORDER[f.severity], reverse=True)
    return findings


# Import rule modules for their registration side effects.
from . import (  # noqa: E402,F401
    broken_references,
    circular_references,
    complexity,
    error_values,
    external_links,
    hardcoded_values,
    hidden_content,
    inconsistent_formulas,
    opaque_content,
    overwritten_formulas,
    suspicious_ranges,
    volatile_functions,
)
