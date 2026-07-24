import json
from pathlib import Path

from excel_auditor.cli import main


def test_cli_audit(demo_paths, tmp_path: Path, capsys):
    _, v2 = demo_paths
    out_json = tmp_path / "audit.json"
    out_html = tmp_path / "audit.html"
    code = main(
        [
            "audit", str(v2),
            "--output-dir", str(tmp_path / "artifacts"),
            "--json-output", str(out_json),
            "--html-output", str(out_html),
        ]
    )
    assert code == 0
    payload = json.loads(out_json.read_text())
    assert payload["findings"]
    assert "<html" in out_html.read_text()
    out = capsys.readouterr().out
    assert "Review priority: HIGH" in out
    assert "http://localhost:8000/reports/" in out
    # stored copies exist in the report store
    stored = list((tmp_path / "artifacts" / "reports").glob("*.html"))
    assert len(stored) == 1


def test_cli_compare(demo_paths, tmp_path: Path, capsys):
    v1, v2 = demo_paths
    out_json = tmp_path / "cmp.json"
    code = main(
        [
            "compare", str(v1), str(v2),
            "--output-dir", str(tmp_path / "artifacts"),
            "--json-output", str(out_json),
        ]
    )
    assert code == 0
    payload = json.loads(out_json.read_text())
    assert payload["summary"]["total_cell_changes"] > 0
    out = capsys.readouterr().out
    assert "Review priority: HIGH" in out
    assert "formula_to_constant" in out
    assert "Report:" in out


def test_cli_demo(tmp_path: Path):
    target = tmp_path / "demo"
    code = main(["demo", "--dir", str(target)])
    assert code == 0
    assert (target / "financial_model_v1.xlsx").exists()
    assert (target / "financial_model_v2.xlsx").exists()
    assert (target / "comparison.json").exists()
    assert (target / "comparison.html").exists()
    assert (target / "audit_v2.json").exists()


def test_cli_error_handling(tmp_path: Path, capsys):
    bad = tmp_path / "bad.xlsx"
    bad.write_text("nope")
    code = main(["audit", str(bad), "--output-dir", str(tmp_path / "artifacts")])
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_cli_verbose_lists_everything(demo_paths, tmp_path: Path, capsys):
    _, v2 = demo_paths
    code = main(
        ["audit", str(v2), "--output-dir", str(tmp_path / "artifacts"), "--verbose"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "… and" not in out  # nothing truncated in verbose mode
