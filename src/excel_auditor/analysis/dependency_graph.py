"""Cell dependency graph.

Nodes are (sheet_name, coordinate) pairs. Edges run from a referenced cell to
the formula cell that depends on it. External workbook references are kept in
a side table and never traversed. Traversal is BFS with a visited set, so
cycles cannot crash it.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from collections.abc import Iterator
from dataclasses import dataclass, field

from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.cell import coordinate_from_string

from ..models import DependencyImpact, WorkbookInventory
from ..parsing.formula_tokenizer import reference_tokens
from ..parsing.reference_parser import parse_reference

logger = logging.getLogger(__name__)

Key = tuple[str, str]  # (sheet name, coordinate) e.g. ("P&L", "B3")

# Heuristics for "output-like" cells (see plan: no perfect semantic classification).
OUTPUT_SHEET_KEYWORDS = (
    "summary",
    "dashboard",
    "report",
    "p&l",
    "pnl",
    "balance",
    "cash flow",
    "cashflow",
    "forecast",
    "budget",
)
OUTPUT_LABEL_KEYWORDS = (
    "total",
    "ebitda",
    "revenue",
    "profit",
    "cash",
    "margin",
    "net",
    "subtotal",
)
MANY_DEPENDENTS_THRESHOLD = 15


@dataclass
class DependencyGraph:
    dependents: dict[Key, set[Key]] = field(default_factory=lambda: defaultdict(set))
    precedents: dict[Key, set[Key]] = field(default_factory=lambda: defaultdict(set))
    external_refs: dict[Key, set[str]] = field(default_factory=lambda: defaultdict(set))
    truncated_ranges: int = 0

    # ------------------------------------------------------------------ build

    @classmethod
    def build(
        cls, inventory: WorkbookInventory, *, max_range_cells: int = 10_000
    ) -> DependencyGraph:
        graph = cls()
        sheet_by_upper = {s.name.upper(): s for s in inventory.sheets}

        for sheet in inventory.sheets:
            for record in sheet.formula_cells:
                dependent: Key = (sheet.name, record.coordinate)
                assert record.formula is not None
                for token in reference_tokens(record.formula):
                    parsed = parse_reference(token.value)
                    if parsed is None:
                        continue
                    if parsed.is_external:
                        graph.external_refs[dependent].add(parsed.raw)
                        continue

                    resolved = (
                        sheet_by_upper.get(parsed.sheet.upper())
                        if parsed.sheet is not None
                        else sheet
                    )
                    if resolved is None:
                        continue  # reference to a sheet we cannot resolve
                    target_sheet = resolved

                    r1 = parsed.start.row
                    c1 = parsed.start.column
                    r2 = parsed.end.row if parsed.end else r1
                    c2 = parsed.end.column if parsed.end else c1
                    # Whole-column/row refs: clamp to the sheet's used range.
                    r1 = 1 if r1 is None else r1
                    c1 = 1 if c1 is None else c1
                    r2 = target_sheet.max_row if r2 is None else r2
                    c2 = target_sheet.max_column if c2 is None else c2
                    r1, r2 = min(r1, r2), max(r1, r2)
                    c1, c2 = min(c1, c2), max(c1, c2)
                    r2 = min(r2, max(target_sheet.max_row, r1))
                    c2 = min(c2, max(target_sheet.max_column, c1))

                    area = (r2 - r1 + 1) * (c2 - c1 + 1)
                    if area > max_range_cells:
                        graph.truncated_ranges += 1
                        r2 = min(r2, r1 + max_range_cells - 1)
                        c2 = c1  # keep it a bounded strip rather than exploding

                    for r in range(r1, r2 + 1):
                        for c in range(c1, c2 + 1):
                            referenced: Key = (target_sheet.name, f"{get_column_letter(c)}{r}")
                            if referenced == dependent:
                                continue
                            graph.dependents[referenced].add(dependent)
                            graph.precedents[dependent].add(referenced)
        return graph

    # -------------------------------------------------------------- traversal

    def transitive_dependents(self, key: Key) -> set[Key]:
        seen: set[Key] = set()
        queue: deque[Key] = deque(self.dependents.get(key, ()))
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            queue.extend(self.dependents.get(node, ()))
        return seen

    def cycles(self) -> list[list[Key]]:
        """All strongly connected components of size > 1 (plus self-loops).

        Iterative Tarjan - no recursion, safe on large graphs.
        """
        adjacency = self.dependents
        index: dict[Key, int] = {}
        low: dict[Key, int] = {}
        on_stack: set[Key] = set()
        stack: list[Key] = []
        counter = 0
        components: list[list[Key]] = []

        for root in list(adjacency.keys()):
            if root in index:
                continue
            work: list[tuple[Key, Iterator[Key]]] = [(root, iter(adjacency.get(root, ())))]
            index[root] = low[root] = counter
            counter += 1
            stack.append(root)
            on_stack.add(root)

            while work:
                node, children = work[-1]
                advanced = False
                for child in children:
                    if child not in index:
                        index[child] = low[child] = counter
                        counter += 1
                        stack.append(child)
                        on_stack.add(child)
                        work.append((child, iter(adjacency.get(child, ()))))
                        advanced = True
                        break
                    if child in on_stack:
                        low[node] = min(low[node], index[child])
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    component: list[Key] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        component.append(w)
                        if w == node:
                            break
                    if len(component) > 1 or component[0] in adjacency.get(component[0], set()):
                        components.append(component)
        return components


# ------------------------------------------------------------------- impact


def _looks_like_output(
    inventory: WorkbookInventory, graph: DependencyGraph, key: Key
) -> str | None:
    """Return a reason string when the cell looks like a model output, else None."""
    sheet_name, coordinate = key
    lowered = sheet_name.lower()
    for keyword in OUTPUT_SHEET_KEYWORDS:
        if keyword in lowered:
            return f"on output-like sheet '{sheet_name}'"

    sheet = inventory.sheet(sheet_name)
    if sheet is not None:
        try:
            col_letter, row = coordinate_from_string(coordinate)
            col = column_index_from_string(col_letter)
        except ValueError:
            return None
        neighbours: list[str] = []
        for delta in range(1, 4):
            if col - delta >= 1:
                neighbours.append(f"{get_column_letter(col - delta)}{row}")
            if row - delta >= 1:
                neighbours.append(f"{col_letter}{row - delta}")
        for coord in neighbours:
            record = sheet.cells.get(coord)
            if record is not None and isinstance(record.value, str):
                text = record.value.lower()
                if any(k in text for k in OUTPUT_LABEL_KEYWORDS):
                    return f"near label '{record.value}'"

    if len(graph.dependents.get(key, ())) >= MANY_DEPENDENTS_THRESHOLD:
        return "has many downstream dependents"
    return None


def impact_for(
    graph: DependencyGraph,
    inventory: WorkbookInventory,
    key: Key,
    *,
    max_output_scan: int = 5_000,
) -> DependencyImpact:
    direct = graph.dependents.get(key, set())
    transitive = graph.transitive_dependents(key)

    outputs: list[str] = []
    for candidate in sorted(transitive)[:max_output_scan]:
        reason = _looks_like_output(inventory, graph, candidate)
        if reason is not None:
            outputs.append(f"{candidate[0]}!{candidate[1]} ({reason})")
            if len(outputs) >= 10:
                break

    return DependencyImpact(
        direct_dependent_count=len(direct),
        transitive_dependent_count=len(transitive),
        affected_sheets=sorted({s for s, _ in transitive}),
        touches_outputs=bool(outputs),
        sample_output_cells=outputs,
        sample_direct_dependents=[f"{s}!{c}" for s, c in sorted(direct)[:20]],
        is_circular=key in transitive,
    )
