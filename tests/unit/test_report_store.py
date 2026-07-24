import dataclasses
from pathlib import Path

from excel_auditor.config import Settings
from excel_auditor.storage.reports import ReportStore


def _store(tmp_path: Path) -> ReportStore:
    settings = dataclasses.replace(Settings(), artifacts_dir=tmp_path / "artifacts")
    return ReportStore(settings)


def test_save_and_load(tmp_path: Path):
    store = _store(tmp_path)
    ref = store.save(kind="audit", report_json='{"a": 1}', report_html="<p>hi</p>")
    assert len(ref.report_id) == 8
    assert ref.url.endswith(f"/reports/{ref.report_id}")
    assert store.load_json(ref.report_id) == '{"a": 1}'
    assert store.load_html(ref.report_id) == "<p>hi</p>"


def test_unknown_and_invalid_ids(tmp_path: Path):
    store = _store(tmp_path)
    store.save(kind="audit", report_json="{}", report_html="x")
    assert store.load_html("deadbeef") is None  # valid shape, missing
    assert store.load_html("../secret") is None
    assert store.load_html("..%2fsecret") is None
    assert store.load_html("") is None
    assert store.load_html("ABCDEF12") is None  # uppercase rejected
