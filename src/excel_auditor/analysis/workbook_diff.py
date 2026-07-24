"""Structural and cell-level comparison of two workbook inventories."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from typing import Any

from ..models import (
    CellChange,
    ChangeType,
    SheetInventory,
    StructuralChange,
    StructuralChangeType,
    WorkbookInventory,
)
from .severity import classify_cell_change


def _values_equal(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b if isinstance(a, bool) and isinstance(b, bool) else False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
    return a == b


def _sheet_signature(sheet: SheetInventory) -> str:
    """Content hash used only for rename inference (sheet name excluded)."""
    digest = hashlib.sha256()
    for coordinate in sorted(sheet.cells):
        record = sheet.cells[coordinate]
        digest.update(f"{coordinate}|{record.formula or ''}|{record.value!r};".encode())
    return digest.hexdigest()


# Inferred-rename criteria (approved decision D3): similarity is the share of
# (coordinate, formula) entries two sheets have in common, measured against
# the larger formula count. All thresholds must hold or the sheets stay
# reported as removed + added.
_MIN_SIMILARITY = 0.80
_MIN_COMPARABLE_FORMULAS = 5
_MIN_MARGIN = 0.10


def _formula_entries(sheet: SheetInventory) -> set[tuple[str, str]]:
    return {
        (coordinate, record.formula)
        for coordinate, record in sheet.cells.items()
        if record.formula
    }


def _similarity(old_entries: set[tuple[str, str]], new_entries: set[tuple[str, str]]) -> float:
    comparable = max(len(old_entries), len(new_entries))
    if comparable < _MIN_COMPARABLE_FORMULAS:
        return 0.0
    return len(old_entries & new_entries) / comparable


def _infer_renames(
    old: WorkbookInventory,
    new: WorkbookInventory,
    removed: list[str],
    added: list[str],
) -> list[tuple[str, str]]:
    """Similarity-based rename inference (D3) over the not-exactly-matched rest.

    A pair is inferred only when similarity >= 0.80 with at least five
    comparable formula cells, and each side is the other's unique best
    candidate by a >= 0.10 margin. Ambiguous or weak cases pair nothing.
    """
    if not removed or not added:
        return []
    old_entries = {
        name: _formula_entries(sheet)
        for name in removed
        if (sheet := old.sheet(name)) is not None
    }
    new_entries = {
        name: _formula_entries(sheet)
        for name in added
        if (sheet := new.sheet(name)) is not None
    }

    by_new: dict[str, list[tuple[float, str]]] = {}
    by_old: dict[str, list[tuple[float, str]]] = {}
    for old_name, entries in old_entries.items():
        for new_name, candidate in new_entries.items():
            similarity = _similarity(entries, candidate)
            if similarity >= _MIN_SIMILARITY:
                by_new.setdefault(new_name, []).append((similarity, old_name))
                by_old.setdefault(old_name, []).append((similarity, new_name))

    def unique_best(scores: list[tuple[float, str]]) -> str | None:
        # Sort by similarity then name so ranking is deterministic; an exact
        # similarity tie fails the margin requirement, so nothing is paired
        # arbitrarily.
        ranked = sorted(scores, key=lambda s: (-s[0], s[1]))
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < _MIN_MARGIN:
            return None
        return ranked[0][1]

    pairs: list[tuple[str, str]] = []
    for new_name in sorted(by_new):
        best_old = unique_best(by_new[new_name])
        if best_old is None:
            continue
        # Require the match to be mutual so one removed sheet can never be
        # claimed by two added sheets (and vice versa).
        if unique_best(by_old[best_old]) != new_name:
            continue
        pairs.append((best_old, new_name))
    return pairs


def _match_sheets(
    old: WorkbookInventory, new: WorkbookInventory
) -> tuple[list[tuple[str, str]], list[str], list[str], list[tuple[str, str, bool]]]:
    """Return (matched name pairs, removed, added, renamed (old, new, inferred))."""
    old_names = {s.name for s in old.sheets}
    new_names = {s.name for s in new.sheets}
    matched = [(n, n) for n in sorted(old_names & new_names)]
    removed = sorted(old_names - new_names)
    added = sorted(new_names - old_names)

    # First, the cheap exact pass: byte-identical content (name excluded).
    exact: list[tuple[str, str]] = []
    if removed and added:
        old_sigs: dict[str, list[str]] = {}
        for name in removed:
            sheet = old.sheet(name)
            if sheet is not None and sheet.cells:
                old_sigs.setdefault(_sheet_signature(sheet), []).append(name)
        for name in added:
            sheet = new.sheet(name)
            if sheet is None or not sheet.cells:
                continue
            candidates = old_sigs.get(_sheet_signature(sheet), [])
            # Only infer a rename when the match is unambiguous.
            if len(candidates) == 1:
                exact.append((candidates[0], name))
    for old_name, new_name in exact:
        removed.remove(old_name)
        added.remove(new_name)
        matched.append((old_name, new_name))

    # Then content-similarity inference (D3) over whatever is left.
    inferred = _infer_renames(old, new, removed, added)
    for old_name, new_name in inferred:
        removed.remove(old_name)
        added.remove(new_name)
        matched.append((old_name, new_name))

    renamed = [(o, n, False) for o, n in exact] + [(o, n, True) for o, n in inferred]
    return matched, removed, added, renamed


_BARE_SHEET_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\Z")


def _sheet_ref_text(name: str) -> str:
    """How a reference to this sheet appears in formula text."""
    if _BARE_SHEET_NAME_RE.match(name):
        return name
    return "'" + name.replace("'", "''") + "'"


def _sheet_rename_mapper(renames: dict[str, str]) -> Callable[[str], str]:
    """Build a formula rewriter mapping old sheet-name references to new ones.

    Purely textual and diff-internal: it is applied to the OLD formula before
    comparison only, so a pure sheet rename does not surface as a wall of
    formula changes. Stored formulas and reports are never mutated. Handles
    both bare (``Inputs!A1``) and quoted (``'Raw Data'!A1``) references; the
    single simultaneous pass keeps chained renames (A->B, B->C) from
    double-mapping.
    """
    lookup: dict[str, str] = {}
    for old_name, new_name in renames.items():
        replacement = _sheet_ref_text(new_name)
        lookup["'" + old_name.replace("'", "''") + "'"] = replacement
        if _BARE_SHEET_NAME_RE.match(old_name):
            lookup[old_name] = replacement
    pattern = re.compile(
        r"(?<![\w.'])("
        + "|".join(re.escape(token) for token in sorted(lookup, key=len, reverse=True))
        + r")(?=!)"
    )
    return lambda formula: pattern.sub(lambda m: lookup[m.group(1)], formula)


def _structural_changes(
    old: WorkbookInventory,
    new: WorkbookInventory,
    matched: list[tuple[str, str]],
    removed: list[str],
    added: list[str],
    renamed: list[tuple[str, str, bool]],
) -> list[StructuralChange]:
    changes: list[StructuralChange] = []

    for name in removed:
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.SHEET_REMOVED,
                sheet_name=name,
                description=f"Worksheet '{name}' was removed.",
            )
        )
    for name in added:
        sheet = new.sheet(name)
        details = {"visibility": sheet.visibility.value if sheet else "visible"}
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.SHEET_ADDED,
                sheet_name=name,
                description=f"Worksheet '{name}' was added"
                + (
                    f" (visibility: {details['visibility']})."
                    if details["visibility"] != "visible"
                    else "."
                ),
                details=details,
            )
        )
    for old_name, new_name, inferred in renamed:
        rename_details: dict[str, Any] = {"old_name": old_name, "new_name": new_name}
        if inferred:
            rename_details["inferred"] = True
            basis = "inferred from content similarity"
        else:
            basis = "identical content"
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.SHEET_RENAMED,
                sheet_name=new_name,
                description=f"Worksheet '{old_name}' appears to have been renamed "
                f"to '{new_name}' ({basis}).",
                details=rename_details,
            )
        )

    # Reordering: compare the relative order of sheets present in both versions.
    old_order = [s.name for s in old.sheets if any(s.name == m[0] for m in matched)]
    mapping = dict(matched)
    projected = [mapping[name] for name in old_order]
    new_order = [s.name for s in new.sheets if s.name in set(projected)]
    if projected != new_order:
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.SHEETS_REORDERED,
                description="Worksheet order changed.",
                details={"old_order": projected, "new_order": new_order},
            )
        )

    for old_name, new_name in matched:
        old_sheet = old.sheet(old_name)
        new_sheet = new.sheet(new_name)
        if old_sheet is None or new_sheet is None:
            continue
        if old_sheet.visibility != new_sheet.visibility:
            changes.append(
                StructuralChange(
                    change_type=StructuralChangeType.SHEET_VISIBILITY_CHANGED,
                    sheet_name=new_name,
                    description=f"Worksheet '{new_name}' visibility changed from "
                    f"{old_sheet.visibility.value} to {new_sheet.visibility.value}.",
                    details={
                        "old": old_sheet.visibility.value,
                        "new": new_sheet.visibility.value,
                    },
                )
            )
        if set(old_sheet.merged_ranges) != set(new_sheet.merged_ranges):
            changes.append(
                StructuralChange(
                    change_type=StructuralChangeType.MERGED_RANGES_CHANGED,
                    sheet_name=new_name,
                    description=f"Merged ranges changed on '{new_name}'.",
                    details={
                        "added": sorted(
                            set(new_sheet.merged_ranges) - set(old_sheet.merged_ranges)
                        ),
                        "removed": sorted(
                            set(old_sheet.merged_ranges) - set(new_sheet.merged_ranges)
                        ),
                    },
                )
            )
        if set(old_sheet.hidden_rows) != set(new_sheet.hidden_rows):
            changes.append(
                StructuralChange(
                    change_type=StructuralChangeType.HIDDEN_ROWS_CHANGED,
                    sheet_name=new_name,
                    description=f"Hidden rows changed on '{new_name}'.",
                    details={
                        "now_hidden": sorted(
                            set(new_sheet.hidden_rows) - set(old_sheet.hidden_rows)
                        ),
                        "now_visible": sorted(
                            set(old_sheet.hidden_rows) - set(new_sheet.hidden_rows)
                        ),
                    },
                )
            )
        if set(old_sheet.hidden_columns) != set(new_sheet.hidden_columns):
            changes.append(
                StructuralChange(
                    change_type=StructuralChangeType.HIDDEN_COLUMNS_CHANGED,
                    sheet_name=new_name,
                    description=f"Hidden columns changed on '{new_name}'.",
                    details={
                        "now_hidden": sorted(
                            set(new_sheet.hidden_columns) - set(old_sheet.hidden_columns)
                        ),
                        "now_visible": sorted(
                            set(old_sheet.hidden_columns) - set(new_sheet.hidden_columns)
                        ),
                    },
                )
            )

    # Named ranges.
    old_ranges = {(r.scope, r.name): r for r in old.named_ranges}
    new_ranges = {(r.scope, r.name): r for r in new.named_ranges}
    for key in sorted(set(old_ranges) - set(new_ranges), key=str):
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.NAMED_RANGE_REMOVED,
                description=f"Named range '{key[1]}' was removed.",
                details={"refers_to": old_ranges[key].refers_to},
            )
        )
    for key in sorted(set(new_ranges) - set(old_ranges), key=str):
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.NAMED_RANGE_ADDED,
                description=f"Named range '{key[1]}' was added.",
                details={"refers_to": new_ranges[key].refers_to},
            )
        )
    for key in sorted(set(old_ranges) & set(new_ranges), key=str):
        if old_ranges[key].refers_to != new_ranges[key].refers_to:
            changes.append(
                StructuralChange(
                    change_type=StructuralChangeType.NAMED_RANGE_CHANGED,
                    description=f"Named range '{key[1]}' now refers to a different range.",
                    details={
                        "old": old_ranges[key].refers_to,
                        "new": new_ranges[key].refers_to,
                    },
                )
            )

    # External links (workbook level).
    old_links = set(old.external_links)
    new_links = set(new.external_links)
    for target in sorted(old_links - new_links):
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.EXTERNAL_LINK_REMOVED,
                description=f"External link removed: {target}",
            )
        )
    for target in sorted(new_links - old_links):
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.EXTERNAL_LINK_ADDED,
                description=f"External link added: {target}",
            )
        )

    if old.has_macros != new.has_macros:
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.MACROS_CHANGED,
                description=(
                    "Macros were added to the workbook."
                    if new.has_macros
                    else "Macros were removed from the workbook."
                ),
            )
        )
    return changes


def _classify_cell(
    old_rec, new_rec, map_old_formula: Callable[[str], str] | None = None
) -> tuple[ChangeType, str] | None:
    """Classify the difference between two cell records (either may be None).

    ``map_old_formula`` rewrites renamed-sheet references in the old formula
    before comparison, so a pure sheet rename is not reported as a change.
    """
    if old_rec is None and new_rec is None:
        return None
    if old_rec is None:
        if new_rec.is_formula:
            return ChangeType.FORMULA_ADDED, "A formula was added to a previously empty cell."
        return ChangeType.VALUE_ADDED, "A value was added to a previously empty cell."
    if new_rec is None:
        if old_rec.is_formula:
            return ChangeType.FORMULA_REMOVED, "A formula was removed (cell is now empty)."
        return ChangeType.VALUE_REMOVED, "A value was removed (cell is now empty)."

    if old_rec.is_formula and new_rec.is_formula:
        old_formula = old_rec.formula
        if map_old_formula is not None and old_formula != new_rec.formula:
            old_formula = map_old_formula(old_formula)
        if old_formula != new_rec.formula:
            if (
                old_rec.normalized_formula is not None
                and old_rec.normalized_formula == new_rec.normalized_formula
            ):
                return (
                    ChangeType.FORMULA_CHANGED,
                    "Formula text changed but the relative structure is identical "
                    "(references likely shifted by an insertion/deletion).",
                )
            return ChangeType.FORMULA_CHANGED, "Formula logic changed."
        if old_rec.style_signature != new_rec.style_signature:
            return ChangeType.FORMATTING_ONLY, "Only formatting changed (formula intact)."
        return None
    if old_rec.is_formula and not new_rec.is_formula:
        return (
            ChangeType.FORMULA_TO_CONSTANT,
            "A formula was replaced by a hardcoded value; the cell no longer recalculates.",
        )
    if not old_rec.is_formula and new_rec.is_formula:
        return ChangeType.CONSTANT_TO_FORMULA, "A hardcoded value was replaced by a formula."

    if not _values_equal(old_rec.value, new_rec.value):
        return ChangeType.VALUE_CHANGED, "Constant value changed."
    if old_rec.style_signature != new_rec.style_signature:
        return ChangeType.FORMATTING_ONLY, "Only formatting changed (value intact)."
    return None


def compare_inventories(
    old: WorkbookInventory, new: WorkbookInventory
) -> tuple[list[StructuralChange], list[CellChange]]:
    matched, removed, added, renamed = _match_sheets(old, new)
    structural = _structural_changes(old, new, matched, removed, added, renamed)

    # Rename-aware formula comparison: on a renamed pair (exact or inferred),
    # references to the old sheet name compare equal to the new name.
    rename_map = {o: n for o, n, _inferred in renamed}
    map_old_formula = _sheet_rename_mapper(rename_map) if rename_map else None

    cell_changes: list[CellChange] = []
    for old_name, new_name in sorted(matched, key=lambda pair: pair[1]):
        old_sheet = old.sheet(old_name)
        new_sheet = new.sheet(new_name)
        if old_sheet is None or new_sheet is None:
            continue
        for coordinate in sorted(
            set(old_sheet.cells) | set(new_sheet.cells),
            key=lambda c: (len(c), c),
        ):
            old_rec = old_sheet.cells.get(coordinate)
            new_rec = new_sheet.cells.get(coordinate)
            classified = _classify_cell(old_rec, new_rec, map_old_formula)
            if classified is None:
                continue
            change_type, explanation = classified
            normalized_equal = bool(
                old_rec is not None
                and new_rec is not None
                and old_rec.normalized_formula is not None
                and old_rec.normalized_formula == new_rec.normalized_formula
            )
            severity, confidence = classify_cell_change(
                change_type, normalized_equal=normalized_equal
            )
            cell_changes.append(
                CellChange(
                    sheet_name=new_name,
                    coordinate=coordinate,
                    change_type=change_type,
                    old_value=old_rec.value if old_rec else None,
                    new_value=new_rec.value if new_rec else None,
                    old_formula=old_rec.formula if old_rec else None,
                    new_formula=new_rec.formula if new_rec else None,
                    normalized_old_formula=old_rec.normalized_formula if old_rec else None,
                    normalized_new_formula=new_rec.normalized_formula if new_rec else None,
                    severity=severity,
                    confidence=confidence,
                    explanation=explanation,
                )
            )
    return structural, cell_changes
