"""EXCEL-005: a crashed rule must be visible in the delivered report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_workbook
from excel_auditor.analysis.rules import base as rules_base
from excel_auditor.reporting.html_report import render_audit_html, render_comparison_html
from excel_auditor.reporting.json_report import to_json
from excel_auditor.services import audit_workbook, compare_workbooks

_WARNING_TEXT = "Analysis coverage incomplete"


class _ExplodingRule(rules_base.Rule):
    rule_id = "EA-TST-999"
    title = "Always crashes"
    description = "Test-only rule that raises unconditionally."

    def run(self, ctx):  # noqa: ARG002 - signature fixed by the Rule ABC
        raise RuntimeError("boom")


@pytest.fixture
def exploding_rule(monkeypatch: pytest.MonkeyPatch) -> type[rules_base.Rule]:
    """Temporarily register a crashing rule; monkeypatch restores ALL_RULES."""
    monkeypatch.setattr(
        rules_base, "ALL_RULES", [*rules_base.ALL_RULES, _ExplodingRule]
    )
    return _ExplodingRule


def _fixture_paths(tmp_path: Path) -> tuple[Path, Path]:
    old = make_workbook(tmp_path / "old.xlsx", {"S": {"A1": 1, "B1": "=A1*2"}})
    new = make_workbook(tmp_path / "new.xlsx", {"S": {"A1": 2, "B1": "=A1*3"}})
    return old, new


def test_audit_surfaces_crashed_rule(tmp_path: Path, exploding_rule):
    old, _ = _fixture_paths(tmp_path)
    report = audit_workbook(old)

    assert report.failed_rules == ["EA-TST-999"]
    assert any("EA-TST-999" in entry for entry in report.limitations)
    assert any("failed to run" in driver for driver in report.risk_drivers)

    payload = json.loads(to_json(report))
    assert payload["failed_rules"] == ["EA-TST-999"]

    html = render_audit_html(report)
    assert _WARNING_TEXT in html
    assert "EA-TST-999" in html


def test_comparison_surfaces_crashed_rule(tmp_path: Path, exploding_rule):
    old, new = _fixture_paths(tmp_path)
    report = compare_workbooks(old, new)

    assert report.failed_rules == ["EA-TST-999"]
    assert any("EA-TST-999" in entry for entry in report.limitations)
    assert any("failed to run" in driver for driver in report.risk_drivers)

    payload = json.loads(to_json(report))
    assert payload["failed_rules"] == ["EA-TST-999"]

    html = render_comparison_html(report)
    assert _WARNING_TEXT in html
    assert "EA-TST-999" in html


def test_other_rules_unaffected_by_crashed_rule(tmp_path: Path, monkeypatch):
    old, _ = _fixture_paths(tmp_path)
    clean = audit_workbook(old)
    monkeypatch.setattr(
        rules_base, "ALL_RULES", [*rules_base.ALL_RULES, _ExplodingRule]
    )
    crashed = audit_workbook(old)
    # Per-rule isolation: every other rule's findings survive intact.
    assert [f.rule_id for f in crashed.findings] == [f.rule_id for f in clean.findings]
    assert crashed.findings_by_severity == clean.findings_by_severity
    assert crashed.risk_level == clean.risk_level


def test_clean_run_has_no_failed_rule_noise(tmp_path: Path):
    old, new = _fixture_paths(tmp_path)

    audit = audit_workbook(old)
    assert audit.failed_rules == []
    assert not any("failed to run" in driver for driver in audit.risk_drivers)
    assert not any("crashed" in entry for entry in audit.limitations)
    assert _WARNING_TEXT not in render_audit_html(audit)

    comparison = compare_workbooks(old, new)
    assert comparison.failed_rules == []
    assert not any("failed to run" in driver for driver in comparison.risk_drivers)
    assert not any("crashed" in entry for entry in comparison.limitations)
    assert _WARNING_TEXT not in render_comparison_html(comparison)
