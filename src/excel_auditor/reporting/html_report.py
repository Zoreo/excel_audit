"""Human-readable HTML reports.

All workbook-derived content is rendered through Jinja2 with autoescaping on,
so cell values and formulas are always HTML-escaped.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from ..models import AuditReport, ChangeType, Severity, WorkbookComparison
from ..models.enums import SEVERITY_ORDER
from ..models.query import QueryReport
from ..models.schema import SchemaReport

_env = Environment(
    loader=PackageLoader("excel_auditor.reporting", "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
)

_SEVERITY_SEQUENCE = [
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
]


def _common_context() -> dict:
    return {
        "severity_sequence": _SEVERITY_SEQUENCE,
        "severity_order": SEVERITY_ORDER,
        "ChangeType": ChangeType,
        "Severity": Severity,
    }


def render_audit_html(report: AuditReport) -> str:
    template = _env.get_template("audit_report.html.j2")
    findings_by_severity: dict[str, list] = {}
    for finding in report.findings:
        findings_by_severity.setdefault(finding.severity.value, []).append(finding)
    return template.render(
        report=report,
        findings_by_severity=findings_by_severity,
        **_common_context(),
    )


def render_comparison_html(report: WorkbookComparison) -> str:
    template = _env.get_template("comparison_report.html.j2")

    items_by_severity: dict[str, list] = {}
    for item in report.review_items:
        items_by_severity.setdefault(item.severity.value, []).append(item)
    formatting_only = [
        c for c in report.cell_changes if c.change_type == ChangeType.FORMATTING_ONLY
    ]
    return template.render(
        report=report,
        items_by_severity=items_by_severity,
        formatting_only=formatting_only,
        **_common_context(),
    )


def render_schema_html(report: SchemaReport) -> str:
    template = _env.get_template("schema_report.html.j2")
    return template.render(report=report, **_common_context())


def render_query_html(report: QueryReport) -> str:
    template = _env.get_template("query_report.html.j2")
    return template.render(report=report, **_common_context())


def write_html(content: str, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
