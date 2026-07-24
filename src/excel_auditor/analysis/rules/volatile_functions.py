"""Volatile functions: recalculate on every change, results are not reproducible."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from ...models.enums import SEVERITY_ORDER
from ...parsing.formula_tokenizer import function_names
from .base import AuditContext, Rule, register

# Function -> severity rationale: INDIRECT/OFFSET obscure the dependency graph,
# RAND* makes results non-deterministic, NOW/TODAY silently change over time.
VOLATILE_SEVERITY = {
    "INDIRECT": Severity.MEDIUM,
    "OFFSET": Severity.MEDIUM,
    "RAND": Severity.MEDIUM,
    "RANDBETWEEN": Severity.MEDIUM,
    "NOW": Severity.LOW,
    "TODAY": Severity.LOW,
}
_MAX_EXAMPLES = 50


@register
class VolatileFunctionsRule(Rule):
    rule_id = "EA-VOL-001"
    title = "Volatile function"
    description = (
        "Volatile functions recalculate constantly, slow large models down and, "
        "for INDIRECT/OFFSET, hide the true dependency structure."
    )

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for sheet in ctx.inventory.sheets:
            for record in sheet.formula_cells:
                assert record.formula is not None
                used = function_names(record.formula) & VOLATILE_SEVERITY.keys()
                if not used:
                    continue
                worst = max(used, key=lambda f: SEVERITY_ORDER[VOLATILE_SEVERITY[f]])
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title=self.title,
                        description=(
                            f"'{sheet.name}'!{record.coordinate} uses "
                            f"{', '.join(sorted(used))}."
                        ),
                        severity=VOLATILE_SEVERITY[worst],
                        confidence=Confidence.HIGH,
                        location=ctx.location(sheet.name, record.coordinate),
                        evidence={"functions": sorted(used), "formula": record.formula},
                        suggested_action=(
                            "Confirm the volatile function is intentional; prefer INDEX or "
                            "direct references where possible."
                        ),
                    )
                )
                if len(findings) >= _MAX_EXAMPLES:
                    return findings
        return findings
