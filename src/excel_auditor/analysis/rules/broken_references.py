"""#REF! errors inside formulas and named ranges."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from .base import AuditContext, Rule, register

_MAX_EXAMPLES = 50


@register
class BrokenReferencesRule(Rule):
    rule_id = "EA-REF-001"
    title = "Broken reference (#REF!)"
    description = "A formula or named range points at cells that no longer exist."

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for sheet in ctx.inventory.sheets:
            for record in sheet.formula_cells:
                assert record.formula is not None
                if "#REF!" not in record.formula.upper():
                    continue
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title=self.title,
                        description=(
                            f"'{sheet.name}'!{record.coordinate} contains #REF! - the formula "
                            "references deleted cells and cannot compute correctly."
                        ),
                        severity=Severity.HIGH,
                        confidence=Confidence.HIGH,
                        location=ctx.location(sheet.name, record.coordinate),
                        evidence={"formula": record.formula},
                        suggested_action="Rebuild the reference; the original target was deleted.",
                    )
                )
                if len(findings) >= _MAX_EXAMPLES:
                    return findings

        for named in ctx.inventory.named_ranges:
            if named.refers_to and "#REF!" in named.refers_to.upper():
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title=self.title,
                        description=f"Named range '{named.name}' refers to #REF!.",
                        severity=Severity.HIGH,
                        confidence=Confidence.HIGH,
                        evidence={"name": named.name, "refers_to": named.refers_to},
                        suggested_action="Fix or delete the broken named range.",
                    )
                )
        return findings
