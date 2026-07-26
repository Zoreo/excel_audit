"""T13 / D10: PDF export.

WeasyPrint is optional (`excel-auditor[pdf]`): tests that render a real PDF
use ``pytest.importorskip("weasyprint")`` so the suite stays green on
machines without the extra. The missing-extra behavior is tested everywhere
by forcing the lazy import to fail (weasyprint may well be installed here).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import make_workbook
from excel_auditor.cli import main
from excel_auditor.errors import ExcelAuditorError, PdfExportUnavailableError
from excel_auditor.reporting.html_report import render_audit_html
from excel_auditor.reporting.pdf_report import PDF_INSTALL_HINT, render_pdf
from excel_auditor.services import audit_workbook

_SHEETS = {"Data": {"A1": 1, "A2": 10, "B1": "=A1*2+A2", "C1": "=1/0"}}


def _fixture(tmp_path: Path) -> Path:
    return make_workbook(tmp_path / "wb.xlsx", _SHEETS)


def _force_no_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a machine without the [pdf] extra: a ``None`` entry in
    ``sys.modules`` makes the lazy ``import weasyprint`` raise ImportError."""
    monkeypatch.setitem(sys.modules, "weasyprint", None)


# ------------------------------------------------------------- render_pdf


def test_render_pdf_produces_valid_pdf():
    pytest.importorskip("weasyprint")
    pdf = render_pdf("<h1>Hello</h1><p>report body</p>")
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000  # non-trivial document, not an empty shell


def test_render_pdf_of_full_audit_report(tmp_path: Path):
    pytest.importorskip("weasyprint")
    html = render_audit_html(audit_workbook(_fixture(tmp_path)))
    pdf = render_pdf(html)
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_render_pdf_without_weasyprint_raises_actionable_hint(
    monkeypatch: pytest.MonkeyPatch,
):
    _force_no_weasyprint(monkeypatch)
    with pytest.raises(PdfExportUnavailableError) as excinfo:
        render_pdf("<p>x</p>")
    assert str(excinfo.value) == PDF_INSTALL_HINT
    assert "pip install 'excel-auditor[pdf]'" in str(excinfo.value)
    # The CLI's ExcelAuditorError handler (exit code 2) must catch it.
    assert isinstance(excinfo.value, ExcelAuditorError)


# ------------------------------------------------------- footer / print CSS


def test_footer_documents_pdf_determinism_exemption(tmp_path: Path):
    # D10: the exemption must be stated in the report footer, not silent.
    html = render_audit_html(audit_workbook(_fixture(tmp_path)))
    assert "excluded from the byte-determinism" in html
    assert "canonical evidence artifacts" in html


def test_print_stylesheet_ships_with_every_report(tmp_path: Path):
    html = render_audit_html(audit_workbook(_fixture(tmp_path)))
    assert "@media print" in html
    assert "size: A4" in html


# --------------------------------------------------------------------- CLI


def test_cli_audit_writes_pdf_to_path_and_store(tmp_path: Path):
    pytest.importorskip("weasyprint")
    out_pdf = tmp_path / "out" / "audit.pdf"
    code = main(
        [
            "audit", str(_fixture(tmp_path)),
            "--output-dir", str(tmp_path / "artifacts"),
            "--pdf-output", str(out_pdf),
            "--pdf",
        ]
    )
    assert code == 0
    explicit = out_pdf.read_bytes()
    assert explicit.startswith(b"%PDF-")
    assert len(explicit) > 1000
    stored = list((tmp_path / "artifacts" / "reports").glob("*.pdf"))
    assert len(stored) == 1
    assert stored[0].read_bytes().startswith(b"%PDF-")


def test_cli_compare_supports_pdf_output(tmp_path: Path):
    pytest.importorskip("weasyprint")
    old = _fixture(tmp_path)
    new = make_workbook(tmp_path / "wb2.xlsx", {"Data": {"A1": 2, "B1": "=A1*3"}})
    out_pdf = tmp_path / "cmp.pdf"
    code = main(
        [
            "compare", str(old), str(new),
            "--output-dir", str(tmp_path / "artifacts"),
            "--pdf-output", str(out_pdf),
        ]
    )
    assert code == 0
    assert out_pdf.read_bytes().startswith(b"%PDF-")


def test_cli_schema_supports_pdf_store_flag(tmp_path: Path):
    pytest.importorskip("weasyprint")
    code = main(
        [
            "schema", str(_fixture(tmp_path)),
            "--output-dir", str(tmp_path / "artifacts"),
            "--pdf",
        ]
    )
    assert code == 0
    stored = list((tmp_path / "artifacts" / "reports").glob("*.pdf"))
    assert len(stored) == 1
    assert stored[0].read_bytes().startswith(b"%PDF-")


def test_cli_query_and_ask_accept_pdf_flags():
    # Flag wiring only (no execution): every analysis command must parse them.
    from excel_auditor.cli import build_parser

    parser = build_parser()
    for argv in (
        ["query", "wb.xlsx", "--pdf", "--pdf-output", "q.pdf"],
        ["ask", "wb.xlsx", "total?", "--pdf", "--pdf-output", "a.pdf"],
        ["audit", "wb.xlsx", "--pdf"],
        ["compare", "a.xlsx", "b.xlsx", "--pdf"],
        ["schema", "wb.xlsx", "--pdf"],
    ):
        args = parser.parse_args(argv)
        assert args.pdf_store is True


def test_cli_pdf_without_weasyprint_exits_2_with_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    _force_no_weasyprint(monkeypatch)
    code = main(
        [
            "audit", str(_fixture(tmp_path)),
            "--output-dir", str(tmp_path / "artifacts"),
            "--pdf",
        ]
    )
    assert code == 2
    assert PDF_INSTALL_HINT in capsys.readouterr().err
    # Fails before publishing: no half-written report in the store.
    reports_dir = tmp_path / "artifacts" / "reports"
    assert not reports_dir.exists() or not any(reports_dir.iterdir())


def test_cli_html_json_flow_unaffected_without_weasyprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _force_no_weasyprint(monkeypatch)
    out_json = tmp_path / "r.json"
    out_html = tmp_path / "r.html"
    code = main(
        [
            "audit", str(_fixture(tmp_path)),
            "--output-dir", str(tmp_path / "artifacts"),
            "--json-output", str(out_json),
            "--html-output", str(out_html),
        ]
    )
    assert code == 0
    assert out_json.is_file()
    assert out_html.is_file()
    assert not list((tmp_path / "artifacts" / "reports").glob("*.pdf"))
