"""Circular reference detection via the dependency graph."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from .base import AuditContext, Rule, register


@register
class CircularReferencesRule(Rule):
    rule_id = "EA-CIR-001"
    title = "Circular reference"
    description = (
        "Cells that depend on themselves. Unless iterative calculation is "
        "deliberately enabled, results are unreliable."
    )

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for component in ctx.graph.cycles():
            members = [f"{sheet}!{coord}" for sheet, coord in sorted(component)]
            first_sheet, first_coord = sorted(component)[0]
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title=self.title,
                    description=(
                        f"Circular reference involving {len(members)} cell(s): "
                        f"{', '.join(members[:10])}"
                        + ("…" if len(members) > 10 else "")
                        + "."
                    ),
                    severity=Severity.HIGH,
                    confidence=Confidence.HIGH,
                    location=ctx.location(first_sheet, first_coord),
                    related_locations=[
                        ctx.location(sheet, coord) for sheet, coord in sorted(component)[1:20]
                    ],
                    evidence={"cycle_size": len(members), "members": members[:20]},
                    suggested_action=(
                        "Break the cycle, or confirm iterative calculation is intended."
                    ),
                )
            )
        return findings
