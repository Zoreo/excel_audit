"""Inconsistent or missing formulas inside repeated ranges."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from .base import AuditContext, Rule, register


@register
class InconsistentFormulasRule(Rule):
    rule_id = "EA-PAT-002"
    title = "Formula inconsistent with surrounding pattern"
    description = (
        "A formula differs structurally from the repeated pattern around it "
        "(shifted reference, changed function or operator, absolute/relative mix-up)."
    )

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for anomaly in ctx.pattern_anomalies:
            if anomaly.kind != "inconsistent_formula":
                continue
            shifted_note = ""
            if anomaly.shifted_by is not None:
                axis = "row" if anomaly.orientation == "column" else "column"
                shifted_note = (
                    f" The formula matches the pattern when shifted by "
                    f"{anomaly.shifted_by} {axis}(s) - it likely references the wrong {axis}."
                )
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title=self.title,
                    description=(
                        f"'{anomaly.sheet_name}'!{anomaly.coordinate} does not match the "
                        f"surrounding formula pattern {anomaly.expected_normalized}."
                        + shifted_note
                    ),
                    severity=Severity.HIGH,
                    confidence=Confidence.MEDIUM
                    if anomaly.shifted_by is None
                    else Confidence.HIGH,
                    location=ctx.location(anomaly.sheet_name, anomaly.coordinate),
                    evidence={
                        "expected_pattern": anomaly.expected_normalized,
                        "actual_formula": anomaly.actual_formula,
                        "shifted_by": anomaly.shifted_by,
                        "orientation": anomaly.orientation,
                    },
                    suggested_action="Compare the formula against its neighbours and correct it.",
                )
            )
        return findings


@register
class MissingFormulasRule(Rule):
    rule_id = "EA-PAT-003"
    title = "Missing formula inside a repeated block"
    description = "A blank cell interrupts an otherwise consistent formula pattern."

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for anomaly in ctx.pattern_anomalies:
            if anomaly.kind != "missing_formula":
                continue
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title=self.title,
                    description=(
                        f"'{anomaly.sheet_name}'!{anomaly.coordinate} is empty although the "
                        f"cells around it share the formula pattern "
                        f"{anomaly.expected_normalized}."
                    ),
                    severity=Severity.MEDIUM,
                    confidence=Confidence.MEDIUM,
                    location=ctx.location(anomaly.sheet_name, anomaly.coordinate),
                    evidence={
                        "expected_pattern": anomaly.expected_normalized,
                        "orientation": anomaly.orientation,
                    },
                    suggested_action="Check whether this cell should contain the formula.",
                )
            )
        return findings
