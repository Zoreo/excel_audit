"""Command line interface.

    excel-auditor audit workbook.xlsx
    excel-auditor compare old.xlsx new.xlsx
    excel-auditor schema workbook.xlsx
    excel-auditor query workbook.xlsx --function sum --value-column Оборот ...
    excel-auditor ask workbook.xlsx "What was total revenue in 2025?"
    excel-auditor demo
    excel-auditor serve

Every analysis command validates the input, runs the engine, stores JSON+HTML
reports in the report store (served at {base_url}/reports/{id} once `serve`
is running), prints a concise terminal summary and the report location.
The CLI uses the same application services as the API.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import webbrowser
from pathlib import Path

from pydantic import BaseModel

from . import __version__
from .config import Settings, get_settings
from .errors import ExcelAuditorError
from .llm import UnsupportedQuestionError, get_parser
from .models import AuditReport, WorkbookComparison
from .models.query import (
    AggregateFunction,
    FilterOperator,
    QueryAction,
    QueryFilter,
    QueryOperation,
    QueryReport,
    ResultStatus,
    SpreadsheetQuery,
)
from .models.schema import SchemaReport
from .query_service import answer_query, inspect_schema
from .reporting.html_report import (
    render_audit_html,
    render_comparison_html,
    render_query_html,
    render_schema_html,
    write_html,
)
from .reporting.json_report import to_json, write_json
from .reporting.pdf_report import render_pdf, write_pdf
from .services import audit_workbook, compare_workbooks
from .storage.reports import ReportRef, ReportStore

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_NEEDS_CONFIRMATION = 3


def _iso_date(raw: str):
    from datetime import date

    return date.fromisoformat(raw)


def _iso_datetime(raw: str):
    from datetime import datetime

    return datetime.fromisoformat(raw)


def _settings_for(args: argparse.Namespace) -> Settings:
    settings = get_settings()
    if getattr(args, "output_dir", None):
        settings = dataclasses.replace(settings, artifacts_dir=Path(args.output_dir))
    return settings


def _publish(
    report: BaseModel,
    html: str,
    *,
    kind: str,
    args: argparse.Namespace,
    settings: Settings,
) -> ReportRef:
    # Render the PDF (if requested) before anything is written so a missing
    # [pdf] extra fails cleanly without leaving a half-published report.
    pdf_to_store = bool(getattr(args, "pdf_store", False))
    pdf_output = getattr(args, "pdf_output", None)
    pdf_bytes: bytes | None = render_pdf(html) if (pdf_to_store or pdf_output) else None
    store = ReportStore(settings)
    ref = store.save(
        kind=kind,
        report_json=to_json(report),
        report_html=html,
        report_pdf=pdf_bytes if pdf_to_store else None,
    )
    if getattr(args, "json_output", None):
        write_json(report, args.json_output)
        print(f"JSON copy written to {args.json_output}")
    if getattr(args, "html_output", None):
        write_html(html, args.html_output)
        print(f"HTML copy written to {args.html_output}")
    if pdf_output and pdf_bytes is not None:
        write_pdf(pdf_bytes, pdf_output)
        print(f"PDF copy written to {pdf_output}")
    print("Report:")
    print(f"  {ref.url}")
    print(f"  {ref.html_path}")
    if ref.pdf_path is not None:
        print(f"  {ref.pdf_path}")
    if getattr(args, "open_report", False):
        webbrowser.open(ref.html_path.as_uri())
    return ref


def _notify_teams(
    settings: Settings, ref: ReportRef, report: AuditReport | WorkbookComparison
) -> int:
    """Post the report card to the configured Teams incoming webhook."""
    from .integrations.teams import post_report_card

    try:
        status = post_report_card(settings, ref, report)
    except Exception as exc:  # noqa: BLE001 - report published; notification failed
        print(f"Teams notification failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"Teams notification posted (HTTP {status}).")
    return EXIT_OK


# ------------------------------------------------------------------- audit


def _print_audit_summary(report: AuditReport, *, verbose: bool) -> None:
    print("Workbook audit complete.")
    print()
    print(f"Review priority: {report.risk_level.upper()}")
    for driver in report.risk_drivers:
        print(f"  {driver}")
    print()
    shown = report.findings if verbose else report.findings[:5]
    for finding in shown:
        where = finding.location.display() if finding.location else "workbook"
        print(f"  [{finding.severity.value:>8}] {finding.rule_id} {where}: {finding.title}")
    hidden = len(report.findings) - len(shown)
    if hidden > 0:
        print(f"  … and {hidden} more (see full report or use --verbose)")
    print()


def _cmd_audit(args: argparse.Namespace) -> int:
    settings = _settings_for(args)
    report = audit_workbook(
        args.workbook,
        settings=settings,
        generated_at=getattr(args, "generated_at", None),
    )
    _print_audit_summary(report, verbose=args.verbose)
    ref = _publish(
        report, render_audit_html(report), kind="audit", args=args, settings=settings
    )
    if getattr(args, "notify_teams", False):
        return _notify_teams(settings, ref, report)
    return EXIT_OK


# ------------------------------------------------------------------ compare


def _print_comparison_summary(report: WorkbookComparison, *, verbose: bool) -> None:
    print("Comparison complete.")
    print()
    print(f"Review priority: {report.risk_level.upper()}")
    for driver in report.risk_drivers:
        print(f"  {driver}")
    print()
    print(
        f"{report.summary.total_review_items} review item(s), "
        f"{report.summary.high_impact_changes} high-impact, "
        f"{report.summary.total_cell_changes} cell change(s), "
        f"{report.summary.structural_change_count} structural"
    )
    for change_type, count in sorted(report.summary.changes_by_type.items()):
        print(f"  {change_type:<22} {count}")
    print()
    shown = report.review_items if verbose else report.review_items[:5]
    for item in shown:
        print(f"  [{item.severity.value:>8}] {item.display_location()}: {item.title}")
    hidden = len(report.review_items) - len(shown)
    if hidden > 0:
        print(f"  … and {hidden} more (see full report or use --verbose)")
    print()


def _cmd_compare(args: argparse.Namespace) -> int:
    settings = _settings_for(args)
    report = compare_workbooks(
        args.old,
        args.new,
        settings=settings,
        generated_at=getattr(args, "generated_at", None),
    )
    _print_comparison_summary(report, verbose=args.verbose)
    ref = _publish(
        report,
        render_comparison_html(report),
        kind="comparison",
        args=args,
        settings=settings,
    )
    if getattr(args, "notify_teams", False):
        return _notify_teams(settings, ref, report)
    return EXIT_OK


# ------------------------------------------------------------------- schema


def _print_schema_summary(report: SchemaReport, *, verbose: bool) -> None:
    print("Workbook schema detected.")
    print()
    schema = report.workbook_schema
    for warning in schema.warnings:
        print(f"  ! {warning}")
    for table in schema.tables:
        print(f"Sheet: {table.sheet_name}")
        print(f"Table: {table.ref}")
        print(f"Rows: {table.row_count}")
        print()
        print("Columns:")
        for column in table.columns:
            extra = f" ({column.currency})" if column.currency else ""
            print(f"- {column.name}: {column.type.value}{extra}")
        if verbose and table.notes:
            for note in table.notes:
                print(f"  note: {note}")
        print()
    if not schema.tables:
        print("No tables with a recognizable header row were detected.")
        print()


def _cmd_schema(args: argparse.Namespace) -> int:
    settings = _settings_for(args)
    report = inspect_schema(args.workbook, settings=settings)
    _print_schema_summary(report, verbose=args.verbose)
    _publish(
        report, render_schema_html(report), kind="schema", args=args, settings=settings
    )
    return EXIT_OK


# ------------------------------------------------------------- query & ask


def _print_query_result(report: QueryReport) -> None:
    result = report.result
    if report.question:
        print(f"Question: {report.question}")
    if result.status == ResultStatus.CANNOT_ANSWER:
        print("Cannot answer safely.")
        if result.message:
            print(result.message)
        return
    if result.formatted_value is not None:
        print(f"Result: {result.formatted_value}")
    if result.message:
        print(result.message)
    for row in result.groups:
        key = ", ".join(f"{k}={v}" for k, v in row.key.items())
        print(f"  {key}: {row.value}  ({row.rows} rows)")
    print()
    print(f"Status: {result.status.value.replace('_', ' ').title()}")
    provenance = result.provenance
    print()
    print("Calculated using:")
    if provenance.workbook:
        print(f"- Workbook: {provenance.workbook}")
    if provenance.sheet:
        print(f"- Sheet: {provenance.sheet}")
    if provenance.table_ref:
        print(f"- Table: {provenance.table_ref}")
    if provenance.value_column:
        print(f"- Value column: {provenance.value_column}")
    if provenance.date_column:
        print(f"- Date column: {provenance.date_column}")
    if provenance.operation:
        function = f" ({provenance.function})" if provenance.function else ""
        print(f"- Operation: {provenance.operation}{function}")
    for flt in provenance.filters:
        print(f"- Filter: {flt}")
    if provenance.group_by:
        print(f"- Grouped by: {', '.join(provenance.group_by)}")
    print(f"- Rows included: {provenance.rows_included}")
    if provenance.rows_excluded_blank:
        print(f"- Blank values excluded: {provenance.rows_excluded_blank}")
    if provenance.rows_excluded_total_rows:
        print(f"- Total rows excluded: {provenance.rows_excluded_total_rows}")
    if provenance.currency:
        print(f"- Currency: {provenance.currency}")
    for assumption in provenance.assumptions:
        print(f"- Assumption: {assumption}")
    for warning in provenance.warnings:
        print(f"- Warning: {warning}")
    print()


def _confirmation_loop(
    run,  # callable(choices: list[int]) -> QueryReport
    *,
    preset_choices: list[int],
    interactive: bool,
) -> tuple[QueryReport, int]:
    """Re-run the query, feeding user choices until it stops asking."""
    choices = list(preset_choices)
    while True:
        report = run(choices)
        result = report.result
        if result.status != ResultStatus.NEEDS_CONFIRMATION:
            return report, EXIT_OK
        print(result.message or "Confirmation required.")
        if not interactive:
            print()
            print(
                "Re-run with --choice N to select an option "
                "(repeat --choice for successive questions)."
            )
            return report, EXIT_NEEDS_CONFIRMATION
        raw = input(f"Select [1-{len(result.candidates)}]: ").strip()
        try:
            picked = int(raw)
        except ValueError:
            print("Not a number; aborting.")
            return report, EXIT_NEEDS_CONFIRMATION
        if not 1 <= picked <= len(result.candidates):
            print("Out of range; aborting.")
            return report, EXIT_NEEDS_CONFIRMATION
        choices.append(picked)


def _cmd_query(args: argparse.Namespace) -> int:
    settings = _settings_for(args)
    filters = []
    if args.filter_column and args.filter_op:
        filters.append(
            QueryFilter(
                column=args.filter_column,
                operator=FilterOperator(args.filter_op),
                value=args.filter_value,
            )
        )
    query = SpreadsheetQuery(
        operation=QueryOperation(args.operation),
        function=AggregateFunction(args.function) if args.function else None,
        requested_metric=args.value_column,
        filters=filters,
        group_by=args.group_by or [],
        source_sheet_hint=args.sheet,
        date_column_hint=args.date_column,
        horizon_days=args.horizon_days,
    )

    def run(choices: list[int]) -> QueryReport:
        return answer_query(
            args.workbook,
            query,
            exact_columns=True,
            choices=choices,
            reference_date=args.reference_date,
            settings=settings,
        )

    report, code = _confirmation_loop(
        run,
        preset_choices=args.choice or [],
        interactive=sys.stdin.isatty() and not args.no_input,
    )
    if report.result.status != ResultStatus.NEEDS_CONFIRMATION:
        _print_query_result(report)
        _publish(
            report, render_query_html(report), kind="query", args=args, settings=settings
        )
    if report.result.status == ResultStatus.CANNOT_ANSWER:
        return EXIT_ERROR
    return code


def _cmd_ask(args: argparse.Namespace) -> int:
    settings = _settings_for(args)
    schema_report = inspect_schema(args.workbook, settings=settings)
    parser = get_parser(args.parser)
    try:
        query = parser.parse(args.question, schema_report.workbook_schema)
    except UnsupportedQuestionError as exc:
        print("Cannot answer safely.")
        print(str(exc))
        return EXIT_ERROR

    # Workbook-analysis actions route to their dedicated flows.
    if query.action == QueryAction.AUDIT_WORKBOOK:
        return _cmd_audit(args)

    def run(choices: list[int]) -> QueryReport:
        return answer_query(
            args.workbook,
            query,
            question=args.question,
            exact_columns=False,
            choices=choices,
            reference_date=args.reference_date,
            settings=settings,
        )

    report, code = _confirmation_loop(
        run,
        preset_choices=args.choice or [],
        interactive=sys.stdin.isatty() and not args.no_input,
    )
    if report.result.status != ResultStatus.NEEDS_CONFIRMATION:
        _print_query_result(report)
        _publish(
            report, render_query_html(report), kind="query", args=args, settings=settings
        )
    if report.result.status == ResultStatus.CANNOT_ANSWER:
        return EXIT_ERROR
    return code


# --------------------------------------------------------------- demo/serve


def _cmd_demo(args: argparse.Namespace) -> int:
    from .demo import generate_demo_workbooks

    directory = Path(args.dir)
    v1, v2 = generate_demo_workbooks(directory)
    print(f"Generated {v1}")
    print(f"Generated {v2}")

    comparison = compare_workbooks(v1, v2)
    write_json(comparison, directory / "comparison.json")
    write_html(render_comparison_html(comparison), directory / "comparison.html")
    audit = audit_workbook(v2)
    write_json(audit, directory / "audit_v2.json")
    write_html(render_audit_html(audit), directory / "audit_v2.html")
    print(f"Reports written to {directory}/comparison.* and {directory}/audit_v2.*")
    print()
    _print_comparison_summary(comparison, verbose=False)
    return EXIT_OK


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "excel_auditor.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
    )
    return EXIT_OK


# ------------------------------------------------------------------- parser


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output-dir", type=Path, help="Artifacts directory for stored reports"
    )
    parser.add_argument(
        "--json-output", "--output", dest="json_output", type=Path,
        help="Also write the JSON report to this exact path",
    )
    parser.add_argument(
        "--html-output", "--html", dest="html_output", type=Path,
        help="Also write the HTML report to this exact path",
    )
    parser.add_argument(
        "--pdf-output", dest="pdf_output", type=Path,
        help="Also write a PDF copy to this exact path (requires the [pdf] extra)",
    )
    parser.add_argument(
        "--pdf", dest="pdf_store", action="store_true",
        help="Also store a PDF copy in the report store (requires the [pdf] extra)",
    )
    parser.add_argument(
        "--open", dest="open_report", action="store_true",
        help="Open the HTML report in the default browser",
    )
    parser.add_argument(
        "--no-open", dest="open_report", action="store_false",
        help="Do not open the report (default)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.set_defaults(open_report=False, verbose=False, pdf_store=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="excel-auditor",
        description="Audit, compare and query Excel workbooks (deterministic, offline).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Risk-audit a single workbook")
    audit.add_argument("workbook", type=Path)
    audit.add_argument(
        "--generated-at", dest="generated_at", type=_iso_datetime,
        help="Report timestamp override (ISO-8601) for reproducible output",
    )
    audit.add_argument(
        "--notify-teams", dest="notify_teams", action="store_true", default=False,
        help="Post a summary card to the configured Teams incoming webhook "
             "(EXCEL_AUDITOR_TEAMS_INCOMING_WEBHOOK_URL)",
    )
    _add_common_flags(audit)
    audit.set_defaults(func=_cmd_audit)

    compare = sub.add_parser("compare", help="Compare two workbook versions")
    compare.add_argument("old", type=Path)
    compare.add_argument("new", type=Path)
    compare.add_argument(
        "--generated-at", dest="generated_at", type=_iso_datetime,
        help="Report timestamp override (ISO-8601) for reproducible output",
    )
    compare.add_argument(
        "--notify-teams", dest="notify_teams", action="store_true", default=False,
        help="Post a summary card to the configured Teams incoming webhook "
             "(EXCEL_AUDITOR_TEAMS_INCOMING_WEBHOOK_URL)",
    )
    _add_common_flags(compare)
    compare.set_defaults(func=_cmd_compare)

    schema = sub.add_parser("schema", help="Detect tables, headers and column types")
    schema.add_argument("workbook", type=Path)
    _add_common_flags(schema)
    schema.set_defaults(func=_cmd_schema)

    query = sub.add_parser("query", help="Run a deterministic structured query")
    query.add_argument("workbook", type=Path)
    query.add_argument("--sheet", help="Sheet hint")
    query.add_argument(
        "--operation",
        default=QueryOperation.AGGREGATE.value,
        choices=[op.value for op in QueryOperation],
    )
    query.add_argument(
        "--function", choices=[fn.value for fn in AggregateFunction], default=None
    )
    query.add_argument("--value-column", dest="value_column")
    query.add_argument("--date-column", dest="date_column")
    query.add_argument("--filter-column", dest="filter_column")
    query.add_argument(
        "--filter-op",
        dest="filter_op",
        choices=[op.value for op in FilterOperator],
    )
    query.add_argument("--filter-value", dest="filter_value")
    query.add_argument("--group-by", dest="group_by", action="append")
    query.add_argument("--horizon-days", dest="horizon_days", type=int)
    query.add_argument(
        "--reference-date", dest="reference_date", type=_iso_date,
        help="Reference date for deadline queries (default: today)",
    )
    query.add_argument(
        "--choice", type=int, action="append",
        help="Pre-answer an ambiguity prompt (repeatable)",
    )
    query.add_argument("--no-input", action="store_true", help="Never prompt")
    _add_common_flags(query)
    query.set_defaults(func=_cmd_query)

    ask = sub.add_parser("ask", help="Ask a constrained free-text question")
    ask.add_argument("workbook", type=Path)
    ask.add_argument("question")
    ask.add_argument(
        "--parser", choices=["rule", "mock"], default=None,
        help="Intent parser (default: rule-based; configurable via env)",
    )
    ask.add_argument(
        "--reference-date", dest="reference_date", type=_iso_date,
        help="Reference date for deadline questions (default: today)",
    )
    ask.add_argument(
        "--choice", type=int, action="append",
        help="Pre-answer an ambiguity prompt (repeatable)",
    )
    ask.add_argument("--no-input", action="store_true", help="Never prompt")
    _add_common_flags(ask)
    ask.set_defaults(func=_cmd_ask)

    demo = sub.add_parser("demo", help="Generate demo workbooks and run a comparison")
    demo.add_argument("--dir", default="demo_workbooks", help="Output directory")
    demo.set_defaults(func=_cmd_demo)

    serve = sub.add_parser("serve", help="Run the API + report server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ExcelAuditorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
