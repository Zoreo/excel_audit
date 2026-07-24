"""Severity/confidence assignment and the transparent risk level.

There is deliberately NO numeric risk score: a "71/100" invites false
precision. Instead the report carries a categorical risk level with an
explicit, one-line rule a reviewer can verify by hand:

    risk level = the highest severity present among review items/findings
      critical -> "critical", high -> "high", medium -> "elevated",
      low -> "low", nothing (or info only) -> "minimal"

together with the drivers behind it ("2 high-severity items, 1 medium…").
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import ChangeType, Confidence, DependencyImpact, Severity
from ..models.enums import CONFIDENCE_ORDER, SEVERITY_ORDER

_BASE_CHANGE_SEVERITY: dict[ChangeType, tuple[Severity, Confidence]] = {
    ChangeType.FORMULA_TO_CONSTANT: (Severity.HIGH, Confidence.HIGH),
    ChangeType.FORMULA_CHANGED: (Severity.MEDIUM, Confidence.HIGH),
    ChangeType.CONSTANT_TO_FORMULA: (Severity.LOW, Confidence.HIGH),
    ChangeType.VALUE_CHANGED: (Severity.LOW, Confidence.HIGH),
    ChangeType.FORMULA_ADDED: (Severity.LOW, Confidence.HIGH),
    ChangeType.FORMULA_REMOVED: (Severity.MEDIUM, Confidence.HIGH),
    ChangeType.VALUE_ADDED: (Severity.INFO, Confidence.HIGH),
    ChangeType.VALUE_REMOVED: (Severity.LOW, Confidence.HIGH),
    ChangeType.FORMATTING_ONLY: (Severity.INFO, Confidence.HIGH),
}

_ESCALATION_ORDER = [
    Severity.INFO,
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
]


def _escalate(severity: Severity) -> Severity:
    idx = _ESCALATION_ORDER.index(severity)
    return _ESCALATION_ORDER[min(idx + 1, len(_ESCALATION_ORDER) - 1)]


def classify_cell_change(
    change_type: ChangeType,
    *,
    normalized_equal: bool = False,
    impact: DependencyImpact | None = None,
) -> tuple[Severity, Confidence]:
    """Base severity per change type, with three documented adjustments:

    - a formula whose raw text changed but whose normalized pattern is
      identical (e.g. references shifted by a row insertion) drops to INFO;
    - a change whose downstream impact reaches output-like cells or 10+
      dependents is escalated one level;
    - a change whose downstream impact may be understated (the workbook's
      formulas use unresolved defined names/tables) and did NOT already
      escalate has its confidence capped at MEDIUM — we cannot confidently
      claim the impact is low.
    """
    severity, confidence = _BASE_CHANGE_SEVERITY[change_type]
    if change_type == ChangeType.FORMULA_CHANGED and normalized_equal:
        severity = Severity.INFO
    if impact is not None and (
        impact.touches_outputs or impact.transitive_dependent_count >= 10
    ):
        if SEVERITY_ORDER[severity] < SEVERITY_ORDER[Severity.HIGH]:
            severity = _escalate(severity)
    elif impact is not None and impact.has_unresolved_names:
        if CONFIDENCE_ORDER[confidence] > CONFIDENCE_ORDER[Confidence.MEDIUM]:
            confidence = Confidence.MEDIUM
    return severity, confidence


_LEVEL_BY_SEVERITY: dict[Severity, str] = {
    Severity.CRITICAL: "critical",
    Severity.HIGH: "high",
    Severity.MEDIUM: "elevated",
    Severity.LOW: "low",
    Severity.INFO: "minimal",
}


def assess_risk(severities: Iterable[Severity], *, noun: str = "item") -> tuple[str, list[str]]:
    """Categorical risk level plus the drivers behind it.

    The rule is documented in the module docstring and repeated verbatim in
    every report so the assessment is verifiable by hand.
    """
    counts: dict[Severity, int] = {}
    for severity in severities:
        counts[severity] = counts.get(severity, 0) + 1

    level = "minimal"
    for severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
        if counts.get(severity):
            level = _LEVEL_BY_SEVERITY[severity]
            break

    drivers = [
        f"{counts[severity]} {severity.value}-severity {noun}(s)"
        for severity in sorted(counts, key=lambda s: SEVERITY_ORDER[s], reverse=True)
        if counts[severity] and severity != Severity.INFO
    ]
    if not drivers:
        drivers = [f"no {noun}s above info severity"]
    return level, drivers
