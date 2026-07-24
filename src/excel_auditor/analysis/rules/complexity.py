"""Unusually long formulas."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from .base import AuditContext, Rule, register

_LENGTH_THRESHOLD = 250
_MAX_EXAMPLES = 20


@register
class LongFormulasRule(Rule):
    rule_id = "EA-CPX-001"
    title = "Unusually long formula"
    description = "Very long formulas are hard to review and frequently hide mistakes."

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for sheet in ctx.inventory.sheets:
            for record in sheet.formula_cells:
                assert record.formula is not None
                if len(record.formula) <= _LENGTH_THRESHOLD:
                    continue
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title=self.title,
                        description=(
                            f"'{sheet.name}'!{record.coordinate} contains a "
                            f"{len(record.formula)}-character formula."
                        ),
                        severity=Severity.LOW,
                        confidence=Confidence.HIGH,
                        location=ctx.location(sheet.name, record.coordinate),
                        evidence={"length": len(record.formula)},
                        suggested_action="Split the calculation into intermediate steps.",
                    )
                )
                if len(findings) >= _MAX_EXAMPLES:
                    return findings
        return findings
