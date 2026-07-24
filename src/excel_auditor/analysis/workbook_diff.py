"""Structural and cell-level comparison of two workbook inventories."""

from __future__ import annotations

import hashlib
import math
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


def _match_sheets(
    old: WorkbookInventory, new: WorkbookInventory
) -> tuple[list[tuple[str, str]], list[str], list[str], list[tuple[str, str]]]:
    """Return (matched name pairs, removed, added, renamed pairs)."""
    old_names = {s.name for s in old.sheets}
    new_names = {s.name for s in new.sheets}
    matched = [(n, n) for n in sorted(old_names & new_names)]
    removed = sorted(old_names - new_names)
    added = sorted(new_names - old_names)

    renamed: list[tuple[str, str]] = []
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
                renamed.append((candidates[0], name))
    for old_name, new_name in renamed:
        removed.remove(old_name)
        added.remove(new_name)
        matched.append((old_name, new_name))
    return matched, removed, added, renamed


def _structural_changes(
    old: WorkbookInventory,
    new: WorkbookInventory,
    matched: list[tuple[str, str]],
    removed: list[str],
    added: list[str],
    renamed: list[tuple[str, str]],
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
    for old_name, new_name in renamed:
        changes.append(
            StructuralChange(
                change_type=StructuralChangeType.SHEET_RENAMED,
                sheet_name=new_name,
                description=f"Worksheet '{old_name}' appears to have been renamed "
                f"to '{new_name}' (identical content).",
                details={"old_name": old_name, "new_name": new_name},
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
    old_rec, new_rec
) -> tuple[ChangeType, str] | None:
    """Classify the difference between two cell records (either may be None)."""
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
        if old_rec.formula != new_rec.formula:
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
            classified = _classify_cell(old_rec, new_rec)
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
