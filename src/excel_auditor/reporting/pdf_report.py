"""PDF rendering of HTML reports (optional extra: ``excel-auditor[pdf]``).

WeasyPrint is imported lazily so the core install never requires it (D10).
When it is missing, :func:`render_pdf` raises a clean
:class:`~excel_auditor.errors.PdfExportUnavailableError` with an actionable
install hint instead of an ImportError traceback.

PDFs are EXCLUDED from the byte-determinism guarantee: WeasyPrint embeds
creation metadata in the output, so two renders of the same report are not
byte-identical. The JSON and HTML reports remain the canonical, deterministic
evidence artifacts (this is also stated in the report footer).
"""

from __future__ import annotations

from pathlib import Path

from ..errors import PdfExportUnavailableError

PDF_INSTALL_HINT = "PDF export requires: pip install 'excel-auditor[pdf]'"


def render_pdf(html: str) -> bytes:
    """Render a self-contained HTML report to PDF bytes.

    Uses the report's ``@media print`` stylesheet (A4, page breaks before
    sections, tables flow across pages instead of scrolling).
    """
    try:
        from weasyprint import HTML
    except ImportError as exc:
        raise PdfExportUnavailableError(PDF_INSTALL_HINT) from exc
    return bytes(HTML(string=html).write_pdf())


def write_pdf(content: bytes, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
