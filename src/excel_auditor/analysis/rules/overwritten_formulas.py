"""Formula overwritten by a hardcoded value inside a repeated range."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from .base import AuditContext, Rule, register


@register
class OverwrittenFormulasRule(Rule):
    rule_id = "EA-PAT-001"
    title = "Formula overwritten with a hardcoded value"
    description = (
        "A cell inside a repeated formula pattern contains a constant instead of "
        "the surrounding formula - a classic silent model break."
    )

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for anomaly in ctx.pattern_anomalies:
            if anomaly.kind != "overwritten_constant":
                continue
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title=self.title,
                    description=(
                        f"'{anomaly.sheet_name}'!{anomaly.coordinate} holds the constant "
                        f"{anomaly.actual_value!r} while {anomaly.run_before + anomaly.run_after} "
                        f"surrounding cells in the same {anomaly.orientation} share the "
                        f"formula pattern {anomaly.expected_normalized}."
                    ),
                    severity=Severity.HIGH,
                    confidence=Confidence.HIGH,
                    location=ctx.location(anomaly.sheet_name, anomaly.coordinate),
                    evidence={
                        "expected_pattern": anomaly.expected_normalized,
                        "actual_value": anomaly.actual_value,
                        "pattern_cells_before": anomaly.run_before,
                        "pattern_cells_after": anomaly.run_after,
                        "orientation": anomaly.orientation,
                    },
                    suggested_action=(
                        "Restore the formula or document why this cell is intentionally "
                        "hardcoded."
                    ),
                )
            )
        return findings
