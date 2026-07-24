"""Content the engine cannot analyze: macros, data connections, protection."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from .base import AuditContext, Rule, register


@register
class MacrosPresentRule(Rule):
    rule_id = "EA-OPQ-001"
    title = "Workbook contains macros"
    description = "VBA macros are present. They are never executed or analyzed by this tool."

    def run(self, ctx: AuditContext) -> list[Finding]:
        if not ctx.inventory.has_macros:
            return []
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                description=(
                    "The workbook contains a VBA project. Macro logic is outside the "
                    "scope of this audit and must be reviewed separately."
                ),
                severity=Severity.MEDIUM,
                confidence=Confidence.HIGH,
                suggested_action="Review the VBA code manually or with a dedicated tool.",
            )
        ]


@register
class DataConnectionsRule(Rule):
    rule_id = "EA-OPQ-002"
    title = "Workbook has external data connections"
    description = "Data connections can refresh cell contents from outside sources."

    def run(self, ctx: AuditContext) -> list[Finding]:
        if not ctx.inventory.has_data_connections:
            return []
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                description="The workbook defines external data connections.",
                severity=Severity.MEDIUM,
                confidence=Confidence.HIGH,
                suggested_action="Review connection definitions and refresh behaviour.",
            )
        ]


@register
class ProtectionRule(Rule):
    rule_id = "EA-OPQ-003"
    title = "Protected workbook or sheets"
    description = "Protection is informational: it limits what a reviewer can inspect in Excel."

    def run(self, ctx: AuditContext) -> list[Finding]:
        protected_sheets = [s.name for s in ctx.inventory.sheets if s.protected]
        if not protected_sheets and not ctx.inventory.workbook_protected:
            return []
        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                description=(
                    "Protection detected"
                    + (" (workbook structure locked)" if ctx.inventory.workbook_protected else "")
                    + (
                        f"; protected sheets: {', '.join(protected_sheets)}."
                        if protected_sheets
                        else "."
                    )
                ),
                severity=Severity.INFO,
                confidence=Confidence.HIGH,
                evidence={
                    "workbook_protected": ctx.inventory.workbook_protected,
                    "protected_sheets": protected_sheets,
                },
                suggested_action="No action needed unless protection is unexpected.",
            )
        ]
