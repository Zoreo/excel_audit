"""Intent parsing layer.

The LLM (or rule-based stand-in) only translates wording into a validated
SpreadsheetQuery. It never computes numbers, never picks between ambiguous
columns, and never sees full workbook contents - only the schema.
"""

from .interface import IntentParser, UnsupportedQuestionError, get_parser

__all__ = ["IntentParser", "UnsupportedQuestionError", "get_parser"]
