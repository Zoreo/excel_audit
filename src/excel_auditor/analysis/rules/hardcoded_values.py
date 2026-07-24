"""Numeric literals buried inside formulas."""

from __future__ import annotations

from ...models import Confidence, Finding, Severity
from ...parsing.formula_tokenizer import (
    SUBTYPE_NUMBER,
    TYPE_OPERAND,
    tokenize,
)
from .base import AuditContext, Rule, register

# Common, usually-harmless literals: counts, unit conversions, percentages.
_WHITELIST = {0.0, 1.0, -1.0, 2.0, 12.0, 100.0, 1000.0, 0.5}
_MAX_EXAMPLES_PER_SHEET = 10


def _suspicious_literals(formula: str) -> list[float]:
    tokens = tokenize(formula)
    if not tokens:
        return []
    literals: list[float] = []
    for tok in tokens:
        if tok.type != TYPE_OPERAND or tok.subtype != SUBTYPE_NUMBER:
            continue
        try:
            value = float(tok.value)
        except ValueError:
            continue
        if value in _WHITELIST:
            continue
        # Flag decimals (rates, margins) and larger integers (amounts).
        if value != int(value) or abs(value) >= 10:
            literals.append(value)
    return literals


@register
class HardcodedValuesRule(Rule):
    rule_id = "EA-HRD-001"
    title = "Hardcoded numbers inside formulas"
    description = (
        "Numeric literals inside formulas bypass the assumptions sheet and are "
        "invisible when reviewing inputs."
    )

    def run(self, ctx: AuditContext) -> list[Finding]:
        findings: list[Finding] = []
        for sheet in ctx.inventory.sheets:
            examples: list[dict[str, object]] = []
            total = 0
            for record in sheet.formula_cells:
                assert record.formula is not None
                literals = _suspicious_literals(record.formula)
                if not literals:
                    continue
                total += 1
                if len(examples) < _MAX_EXAMPLES_PER_SHEET:
                    examples.append(
                        {
                            "cell": record.coordinate,
                            "formula": record.formula,
                            "literals": literals,
                        }
                    )
            if total:
                findings.append(
                    Finding(
                        rule_id=self.rule_id,
                        title=self.title,
                        description=(
                            f"{total} formula(s) on '{sheet.name}' contain hardcoded "
                            "numeric literals."
                        ),
                        severity=Severity.LOW,
                        confidence=Confidence.MEDIUM,
                        location=ctx.location(sheet.name),
                        evidence={"examples": examples, "total": total},
                        suggested_action=(
                            "Move business inputs to a dedicated assumptions area and "
                            "reference them."
                        ),
                    )
                )
        return findings
