"""Structural and cell-level comparison of two workbook inventories."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Any

from openpyxl.utils import get_column_letter

from ..models import (
    CellChange,
    CellRecord,
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


# ------------------------------------------------------------ row alignment
#
# Approved decision D7: rows of a matched sheet pair are aligned with per-row
# signatures + difflib.SequenceMatcher (stdlib, deterministic). Alignment is
# applied only when the sheet has >= 5 data rows on both sides AND the
# matcher's ratio is >= 0.60; otherwise the positional diff runs unchanged.
# Approved decision D8: cells on inserted/removed rows are carried by
# ROWS_INSERTED / ROWS_REMOVED structural changes (one per contiguous run)
# instead of flooding the report with per-cell adds/removes.

_MIN_DATA_ROWS = 5
_MIN_ROW_ALIGNMENT_RATIO = 0.60
_MAX_SAMPLE_CELLS = 5
# Pairing an empty row with a populated one is allowed but weak, so cells
# typed into a previously blank row keep reading as per-cell additions.
_EMPTY_PAIR_SCORE = 0.05
# Rows sharing no content may still pair positionally (a fully retyped row),
# but only when no better alignment exists at all.
_FLOOR_PAIR_SCORE = 0.01
# Replace regions larger than this (old rows x new rows) skip the similarity
# DP and pair positionally; the remainder becomes inserted/removed runs.
_MAX_REPLACE_DP_PAIRS = 10_000

_RowSignature = tuple[Any, ...]
_EMPTY_ROW: _RowSignature = ()


def _cell_signature(record: CellRecord) -> tuple[str, Any]:
    """Alignment identity of one cell: normalized formula or a typed value."""
    if record.is_formula:
        return ("f", record.normalized_formula or record.formula)
    value = record.value
    if isinstance(value, bool):
        return ("b", value)
    if isinstance(value, (int, float)):
        return ("n", float(value))
    if isinstance(value, str):
        return ("s", value)
    return ("o", repr(value))


def _row_map(sheet: SheetInventory) -> dict[int, dict[int, CellRecord]]:
    rows: dict[int, dict[int, CellRecord]] = {}
    for record in sheet.cells.values():
        rows.setdefault(record.row, {})[record.column] = record
    return rows


def _signature_sequence(
    rows: dict[int, dict[int, CellRecord]], used_columns: list[int]
) -> list[_RowSignature]:
    """Signatures for rows 1..last populated row (index i = row i + 1)."""
    sequence: list[_RowSignature] = []
    for row in range(1, max(rows) + 1):
        cells = rows.get(row)
        if not cells:
            sequence.append(_EMPTY_ROW)
        else:
            sequence.append(
                tuple(
                    _cell_signature(cells[column]) if column in cells else None
                    for column in used_columns
                )
            )
    return sequence


def _row_similarity(a: _RowSignature, b: _RowSignature) -> float:
    """Share of populated columns two row signatures agree on (see floors)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return _EMPTY_PAIR_SCORE
    populated = 0
    matches = 0
    for entry_a, entry_b in zip(a, b, strict=True):
        if entry_a is None and entry_b is None:
            continue
        populated += 1
        if entry_a == entry_b:
            matches += 1
    if populated == 0:  # pragma: no cover - non-empty signatures always overlap
        return 1.0
    return max(matches / populated, _FLOOR_PAIR_SCORE)


def _align_replace_region(
    old_rows: list[int],
    new_rows: list[int],
    old_signatures: list[_RowSignature],
    new_signatures: list[_RowSignature],
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Align one `replace` opcode region by content similarity.

    Returns (paired (old_row, new_row) list, removed old rows, inserted new
    rows). A monotonic best-similarity alignment (edit-distance style DP)
    decides which surplus rows are the inserted/removed ones, so an appended
    month pairs the moved total row with its new position instead of pairing
    the total with the new data row. Ties prefer pairing, then removal.
    """
    count_old, count_new = len(old_rows), len(new_rows)
    if count_old * count_new > _MAX_REPLACE_DP_PAIRS:
        shared = min(count_old, count_new)
        return (
            list(zip(old_rows[:shared], new_rows[:shared], strict=False)),
            old_rows[shared:],
            new_rows[shared:],
        )
    score = [
        [_row_similarity(old_signatures[i], new_signatures[j]) for j in range(count_new)]
        for i in range(count_old)
    ]
    best = [[0.0] * (count_new + 1) for _ in range(count_old + 1)]
    for i in range(1, count_old + 1):
        for j in range(1, count_new + 1):
            best[i][j] = max(
                best[i - 1][j - 1] + score[i - 1][j - 1],
                best[i - 1][j],
                best[i][j - 1],
            )
    paired: list[tuple[int, int]] = []
    removed: list[int] = []
    inserted: list[int] = []
    i, j = count_old, count_new
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and best[i][j] == best[i - 1][j - 1] + score[i - 1][j - 1]
        ):
            paired.append((old_rows[i - 1], new_rows[j - 1]))
            i -= 1
            j -= 1
        elif i > 0 and best[i][j] == best[i - 1][j]:
            removed.append(old_rows[i - 1])
            i -= 1
        else:
            inserted.append(new_rows[j - 1])
            j -= 1
    paired.reverse()
    removed.reverse()
    inserted.reverse()
    return paired, removed, inserted


def _align_rows(
    old_rows: dict[int, dict[int, CellRecord]],
    new_rows: dict[int, dict[int, CellRecord]],
) -> tuple[list[tuple[int, int]], list[int], list[int]] | None:
    """Row alignment for one matched sheet pair, or None when the D7 gate
    fails (fewer than 5 data rows on either side, or ratio < 0.60)."""
    if len(old_rows) < _MIN_DATA_ROWS or len(new_rows) < _MIN_DATA_ROWS:
        return None
    used_columns = sorted(
        {column for cells in old_rows.values() for column in cells}
        | {column for cells in new_rows.values() for column in cells}
    )
    old_sequence = _signature_sequence(old_rows, used_columns)
    new_sequence = _signature_sequence(new_rows, used_columns)
    matcher = SequenceMatcher(a=old_sequence, b=new_sequence, autojunk=False)
    if matcher.ratio() < _MIN_ROW_ALIGNMENT_RATIO:
        return None
    paired: list[tuple[int, int]] = []
    removed: list[int] = []
    inserted: list[int] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            paired.extend((i1 + k + 1, j1 + k + 1) for k in range(i2 - i1))
        elif tag == "delete":
            removed.extend(range(i1 + 1, i2 + 1))
        elif tag == "insert":
            inserted.extend(range(j1 + 1, j2 + 1))
        else:  # replace
            region = _align_replace_region(
                list(range(i1 + 1, i2 + 1)),
                list(range(j1 + 1, j2 + 1)),
                old_sequence[i1:i2],
                new_sequence[j1:j2],
            )
            paired.extend(region[0])
            removed.extend(region[1])
            inserted.extend(region[2])
    if removed and inserted:
        removed_signatures = Counter(old_sequence[row - 1] for row in removed)
        inserted_signatures = Counter(new_sequence[row - 1] for row in inserted)
        if removed_signatures == inserted_signatures:
            # Pure row reorder: every "removed" row reappears "inserted"
            # elsewhere, so nothing was actually added or deleted. The
            # positional diff (value changes at the swapped positions) reads
            # better than a remove+insert pair, so fall back.
            return None
    return paired, removed, inserted


def _contiguous_runs(rows: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for row in sorted(rows):
        if runs and row == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], row)
        else:
            runs.append((row, row))
    return runs


def _row_run_changes(
    change_type: StructuralChangeType,
    sheet_name: str,
    rows: list[int],
    row_cells: dict[int, dict[int, CellRecord]],
) -> list[StructuralChange]:
    """One ROWS_INSERTED / ROWS_REMOVED change per contiguous run (D8)."""
    inserted = change_type is StructuralChangeType.ROWS_INSERTED
    changes: list[StructuralChange] = []
    for start, end in _contiguous_runs(rows):
        count = end - start + 1
        samples: list[dict[str, Any]] = []
        for row in range(start, end + 1):
            cells = row_cells.get(row, {})
            for column in sorted(cells):
                if len(samples) >= _MAX_SAMPLE_CELLS:
                    break
                record = cells[column]
                samples.append(
                    {
                        "coordinate": record.coordinate,
                        "formula": record.formula,
                        "value": record.value,
                    }
                )
            if len(samples) >= _MAX_SAMPLE_CELLS:
                break
        position = f"row {start}" if count == 1 else f"rows {start}-{end}"
        suffix = "" if inserted else " (old-version row numbers)"
        changes.append(
            StructuralChange(
                change_type=change_type,
                sheet_name=sheet_name,
                description=(
                    f"{count} row(s) {'inserted' if inserted else 'removed'} "
                    f"at {position} on '{sheet_name}'{suffix}."
                ),
                details={"start_row": start, "count": count, "sample_cells": samples},
            )
        )
    return changes


def _append_cell_change(
    changes: list[CellChange],
    sheet_name: str,
    coordinate: str,
    old_rec: CellRecord | None,
    new_rec: CellRecord | None,
    map_old_formula: Callable[[str], str] | None,
    *,
    suppress_shift_noise: bool = False,
) -> None:
    classified = _classify_cell(old_rec, new_rec, map_old_formula)
    if classified is None:
        return
    change_type, explanation = classified
    normalized_equal = bool(
        old_rec is not None
        and new_rec is not None
        and old_rec.normalized_formula is not None
        and old_rec.normalized_formula == new_rec.normalized_formula
    )
    if suppress_shift_noise and (
        change_type == ChangeType.FORMATTING_ONLY
        or (change_type == ChangeType.FORMULA_CHANGED and normalized_equal)
    ):
        # D8: this pair sits on rows aligned across an insertion/deletion.
        # Reference shifts and cross-row formatting comparisons are alignment
        # artifacts, not edits; genuinely changed logic still differs after
        # normalization and is reported below.
        return
    severity, confidence = classify_cell_change(
        change_type, normalized_equal=normalized_equal
    )
    changes.append(
        CellChange(
            sheet_name=sheet_name,
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
        old_rows = _row_map(old_sheet) if old_sheet.cells else {}
        new_rows = _row_map(new_sheet) if new_sheet.cells else {}
        alignment = _align_rows(old_rows, new_rows) if old_rows and new_rows else None
        if alignment is None:
            # D7 gate failed: fall back to the positional diff, byte-identical
            # to the pre-alignment behavior.
            for coordinate in sorted(
                set(old_sheet.cells) | set(new_sheet.cells),
                key=lambda c: (len(c), c),
            ):
                _append_cell_change(
                    cell_changes,
                    new_name,
                    coordinate,
                    old_sheet.cells.get(coordinate),
                    new_sheet.cells.get(coordinate),
                    map_old_formula,
                )
            continue
        paired, removed_rows, inserted_rows = alignment
        for old_row, new_row in paired:
            old_cells = old_rows.get(old_row, {})
            new_cells = new_rows.get(new_row, {})
            shifted = old_row != new_row
            for column in sorted(set(old_cells) | set(new_cells)):
                _append_cell_change(
                    cell_changes,
                    new_name,
                    f"{get_column_letter(column)}{new_row}",
                    old_cells.get(column),
                    new_cells.get(column),
                    map_old_formula,
                    suppress_shift_noise=shifted,
                )
        structural.extend(
            _row_run_changes(
                StructuralChangeType.ROWS_INSERTED, new_name, inserted_rows, new_rows
            )
        )
        structural.extend(
            _row_run_changes(
                StructuralChangeType.ROWS_REMOVED, new_name, removed_rows, old_rows
            )
        )
    return structural, cell_changes
