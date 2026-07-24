"""External workbook dependencies.

Single rule (EA-EXT-001): the inventory already unifies workbook-level link
targets with targets derived from formula text, so the count reported here is
always the same count shown in the workbook overview. (EA-EXT-002 was merged
into this rule.)
"""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from ...parsing.formula_tokenizer import reference_tokens
from ...parsing.reference_parser import parse_reference
from .base import AuditContext, Rule, register

_MAX_LOCATIONS = 20
_MAX_EXAMPLES = 10


@register
class ExternalDependenciesRule(Rule):
    rule_id = "EA-EXT-001"
    title = "External workbook dependencies"
    description = (
        "The workbook depends on external files; results rely on content that "
        "is not inside this workbook and is never followed by this tool."
    )

    def run(self, ctx: AuditContext) -> list[Finding]:
        targets = ctx.inventory.external_links
        referencing: list[tuple[str, str, str]] = []  # (sheet, coordinate, raw ref)
        for sheet in ctx.inventory.sheets:
            for record in sheet.formula_cells:
                assert record.formula is not None
                for token in reference_tokens(record.formula):
                    parsed = parse_reference(token.value)
                    if parsed is not None and parsed.is_external:
                        referencing.append((sheet.name, record.coordinate, parsed.raw))
                        break  # one entry per formula cell

        if not targets and not referencing:
            return []

        description = f"The workbook depends on {len(targets)} external file(s)"
        if referencing:
            description += f"; {len(referencing)} formula(s) reference them directly"
        description += "."

        return [
            Finding(
                rule_id=self.rule_id,
                title=self.title,
                description=description,
                severity=Severity.MEDIUM,
                confidence=Confidence.HIGH,
                related_locations=[
                    ctx.location(sheet, coordinate)
                    for sheet, coordinate, _ in referencing[:_MAX_LOCATIONS]
                ],
                evidence={
                    "targets": targets[:_MAX_EXAMPLES],
                    "referencing_cells": [
                        {"cell": f"{sheet}!{coordinate}", "reference": raw}
                        for sheet, coordinate, raw in referencing[:_MAX_EXAMPLES]
                    ],
                    "referencing_cell_count": len(referencing),
                },
                suggested_action=(
                    "Confirm the external sources are available, current and trusted; "
                    "consider replacing links with values or internal data."
                ),
            )
        ]
