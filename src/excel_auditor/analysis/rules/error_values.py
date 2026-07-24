"""Excel error values in cells (cached results or literal constants)."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from .base import AuditContext, Rule, register

ERROR_LITERALS = {"#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!"}
_MAX_EXAMPLES = 50


@register
class ErrorValuesRule(Rule):
    rule_id = "EA-ERR-001"
    title = "Cell contains an error value"
    description = "Error values propagate into every downstream calculation."

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for sheet in ctx.inventory.sheets:
            for record in sheet.cells.values():
                value = record.value
                is_error = record.data_type == "e" or (
                    isinstance(value, str) and value.strip().upper() in ERROR_LITERALS
                )
                if not is_error:
                    continue
                literal = str(value).strip().upper() if value is not None else "error"
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title=self.title,
                        description=f"'{sheet.name}'!{record.coordinate} evaluates to {literal}.",
                        # #N/A is often an intentional lookup placeholder.
                        severity=Severity.LOW if literal == "#N/A" else Severity.HIGH,
                        confidence=Confidence.HIGH,
                        location=ctx.location(sheet.name, record.coordinate),
                        evidence={"value": literal, "formula": record.formula},
                        suggested_action="Trace and fix the source of the error.",
                    )
                )
                if len(findings) >= _MAX_EXAMPLES:
                    return findings
        return findings
