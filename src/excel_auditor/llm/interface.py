"""IntentParser protocol and parser selection.

Parsers receive the user question plus the detected WorkbookSchema (sheet
names, table refs, column names/types - never raw cell data) and return a
validated SpreadsheetQuery.

Selection is configuration-driven so an LLM-backed parser can be slotted in
without touching application code:

    EXCEL_AUDITOR_INTENT_PARSER=rule   (default; deterministic, EN + BG)
    EXCEL_AUDITOR_INTENT_PARSER=mock   (tests)

An LLM provider would register here behind the same protocol; it is
deliberately not bundled in this milestone.
"""

from __future__ import annotations

import os
from typing import Protocol

from ..models.query import SpreadsheetQuery
from ..models.schema import WorkbookSchema


class UnsupportedQuestionError(Exception):
    """The question cannot be mapped to a supported deterministic operation."""


class IntentParser(Protocol):
    def parse(self, question: str, schema: WorkbookSchema) -> SpreadsheetQuery: ...


def get_parser(name: str | None = None) -> IntentParser:
    choice = (name or os.environ.get("EXCEL_AUDITOR_INTENT_PARSER", "rule")).lower()
    if choice == "mock":
        from .mock_parser import MockIntentParser

        return MockIntentParser()
    from .rule_parser import RuleBasedIntentParser

    return RuleBasedIntentParser()
