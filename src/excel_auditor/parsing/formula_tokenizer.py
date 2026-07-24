"""Thin, defensive wrapper around openpyxl's formula tokenizer.

We deliberately do not build our own Excel formula interpreter. openpyxl's
tokenizer handles quoted sheet names, strings, error literals and function
nesting well enough for structural analysis of common financial formulas.
"""

from __future__ import annotations

from dataclasses import dataclass

from openpyxl.formula.tokenizer import Token as _OpenpyxlToken
from openpyxl.formula.tokenizer import Tokenizer as _Tokenizer
from openpyxl.formula.tokenizer import TokenizerError

# Re-exported token type/subtype constants.
TYPE_OPERAND = _OpenpyxlToken.OPERAND
TYPE_FUNC = _OpenpyxlToken.FUNC
TYPE_WSPACE = _OpenpyxlToken.WSPACE
SUBTYPE_RANGE = _OpenpyxlToken.RANGE
SUBTYPE_NUMBER = _OpenpyxlToken.NUMBER
SUBTYPE_TEXT = _OpenpyxlToken.TEXT
SUBTYPE_ERROR = _OpenpyxlToken.ERROR
SUBTYPE_OPEN = _OpenpyxlToken.OPEN


@dataclass(frozen=True)
class Token:
    value: str
    type: str
    subtype: str


def tokenize(formula: str) -> list[Token] | None:
    """Tokenize a formula string (including the leading '=').

    Returns None when the formula cannot be tokenized; callers must treat
    that as "opaque formula", never as an error.
    """
    if not isinstance(formula, str) or not formula.startswith("="):
        return None
    try:
        parsed = _Tokenizer(formula)
    except (TokenizerError, IndexError, ValueError):
        return None
    return [Token(value=t.value, type=t.type, subtype=t.subtype) for t in parsed.items]


def function_names(formula: str) -> set[str]:
    """Uppercased names of all functions used in a formula."""
    tokens = tokenize(formula)
    if not tokens:
        return set()
    names: set[str] = set()
    for tok in tokens:
        if tok.type == TYPE_FUNC and tok.subtype == SUBTYPE_OPEN:
            names.add(tok.value.rstrip("(").upper())
    return names


def reference_tokens(formula: str) -> list[Token]:
    """All OPERAND/RANGE tokens (cell refs, ranges, defined names)."""
    tokens = tokenize(formula)
    if not tokens:
        return []
    return [t for t in tokens if t.type == TYPE_OPERAND and t.subtype == SUBTYPE_RANGE]
