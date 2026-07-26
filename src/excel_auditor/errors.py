"""Domain exceptions.

Every user-facing failure should raise one of these so the API and CLI can
translate them into useful errors instead of raw stack traces.
"""


class ExcelAuditorError(Exception):
    """Base class for all domain errors."""


class WorkbookValidationError(ExcelAuditorError):
    """The uploaded file is not a supported, safe Excel workbook."""


class WorkbookLoadError(ExcelAuditorError):
    """The workbook passed validation but could not be parsed."""


class JobNotFoundError(ExcelAuditorError):
    """No job exists with the requested id."""


class PdfExportUnavailableError(ExcelAuditorError):
    """PDF export was requested but the optional [pdf] extra is not installed."""
