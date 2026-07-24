"""Hidden sheets, rows and columns."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity, SheetVisibility
from .base import AuditContext, Rule, register


@register
class HiddenSheetsRule(Rule):
    rule_id = "EA-HID-001"
    title = "Hidden worksheet"
    description = "Hidden or very-hidden worksheets can conceal data or logic from reviewers."

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for sheet in ctx.inventory.sheets:
            if sheet.visibility == SheetVisibility.VISIBLE:
                continue
            very = sheet.visibility == SheetVisibility.VERY_HIDDEN
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title=self.title,
                    description=(
                        f"Worksheet '{sheet.name}' is "
                        f"{'very hidden (only unhidable via VBA/editor)' if very else 'hidden'} "
                        f"and contains {len(sheet.cells)} populated cell(s)."
                    ),
                    severity=Severity.MEDIUM if very else Severity.LOW,
                    confidence=Confidence.HIGH,
                    location=ctx.location(sheet.name),
                    evidence={
                        "visibility": sheet.visibility.value,
                        "populated_cells": len(sheet.cells),
                    },
                    suggested_action="Unhide the sheet and confirm its content is intentional.",
                )
            )
        return findings


@register
class HiddenRowsColumnsRule(Rule):
    rule_id = "EA-HID-002"
    title = "Hidden rows/columns containing data"
    description = "Hidden rows or columns that contain data are easy to overlook in review."

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for sheet in ctx.inventory.sheets:
            rows_with_data = [
                r
                for r in sheet.hidden_rows
                if any(c.row == r for c in sheet.cells.values())
            ]
            cols_with_data = [
                letter
                for letter in sheet.hidden_columns
                if any(c.coordinate.rstrip("0123456789") == letter for c in sheet.cells.values())
            ]
            if not rows_with_data and not cols_with_data:
                continue
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    title=self.title,
                    description=(
                        f"Worksheet '{sheet.name}' hides "
                        f"{len(rows_with_data)} row(s) and {len(cols_with_data)} column(s) "
                        "that contain data."
                    ),
                    severity=Severity.LOW,
                    confidence=Confidence.HIGH,
                    location=ctx.location(sheet.name),
                    evidence={
                        "hidden_rows_with_data": rows_with_data[:50],
                        "hidden_columns_with_data": cols_with_data[:50],
                    },
                    suggested_action="Unhide and review the hidden rows/columns.",
                )
            )
        return findings
