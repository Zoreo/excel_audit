from pathlib import Path

from conftest import make_workbook
from excel_auditor.analysis.dependency_graph import DependencyGraph, impact_for
from excel_auditor.analysis.workbook_inventory import inventory_from_path


def test_direct_and_transitive_dependents(new_inventory):
    graph = DependencyGraph.build(new_inventory)
    # P&L!B3 (COGS) feeds B4 -> B6 -> ... -> Summary
    direct = graph.dependents[("P&L", "B3")]
    assert ("P&L", "B4") in direct
    transitive = graph.transitive_dependents(("P&L", "B3"))
    assert ("P&L", "B6") in transitive
    assert ("Summary", "B4") in transitive
    assert ("Summary", "B5") in transitive


def test_cross_sheet_and_range_edges(new_inventory):
    graph = DependencyGraph.build(new_inventory)
    # Revenue Forecast D7 is inside SUM(D2:D12) on D14
    assert ("Revenue Forecast", "D14") in graph.dependents[("Revenue Forecast", "D7")]
    # P&L B2 references 'Revenue Forecast'!D14 cross-sheet
    assert ("P&L", "B2") in graph.dependents[("Revenue Forecast", "D14")]


def test_impact_touches_outputs(new_inventory):
    graph = DependencyGraph.build(new_inventory)
    impact = impact_for(graph, new_inventory, ("P&L", "B3"))
    assert impact.transitive_dependent_count > 3
    assert "Summary" in impact.affected_sheets
    assert impact.touches_outputs


def test_external_refs_not_traversed(new_inventory):
    graph = DependencyGraph.build(new_inventory)
    externals = graph.external_refs[("Summary", "B7")]
    assert externals  # the benchmark reference is recorded ...
    # ... but no graph node was created for the external workbook
    assert all("Benchmarks" not in sheet for sheet, _ in graph.dependents)


def test_cycle_does_not_crash_and_is_reported(tmp_path: Path):
    path = make_workbook(
        tmp_path / "cycle.xlsx",
        {"Loop": {"A1": "=B1+1", "B1": "=A1+1", "C1": "=A1"}},
    )
    inventory = inventory_from_path(path)
    graph = DependencyGraph.build(inventory)
    # traversal terminates
    transitive = graph.transitive_dependents(("Loop", "A1"))
    assert ("Loop", "A1") in transitive  # reaches itself -> circular
    impact = impact_for(graph, inventory, ("Loop", "A1"))
    assert impact.is_circular
    cycles = graph.cycles()
    assert len(cycles) == 1
    assert {("Loop", "A1"), ("Loop", "B1")} == set(cycles[0])


def test_whole_column_reference_clamped(tmp_path: Path):
    path = make_workbook(
        tmp_path / "wholecol.xlsx",
        {"Data": {"A1": 1, "A2": 2, "A3": 3, "B1": "=SUM(A:A)"}},
    )
    inventory = inventory_from_path(path)
    graph = DependencyGraph.build(inventory)
    assert ("Data", "B1") in graph.dependents[("Data", "A3")]
    # clamped to the used range, not 1M rows
    assert len(graph.precedents[("Data", "B1")]) <= 4
