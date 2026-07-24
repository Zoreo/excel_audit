"""Deterministic mock parser for tests: returns pre-registered queries."""

from __future__ import annotations

from ..models.query import SpreadsheetQuery
from ..models.schema import WorkbookSchema
from .interface import UnsupportedQuestionError


class MockIntentParser:
    def __init__(self, mapping: dict[str, SpreadsheetQuery] | None = None):
        self.mapping = mapping or {}
        self.seen: list[str] = []

    def register(self, question: str, query: SpreadsheetQuery) -> None:
        self.mapping[question] = query

    def parse(self, question: str, schema: WorkbookSchema) -> SpreadsheetQuery:
        self.seen.append(question)
        if question not in self.mapping:
            raise UnsupportedQuestionError(f"Mock parser has no mapping for: {question!r}")
        return self.mapping[question]
