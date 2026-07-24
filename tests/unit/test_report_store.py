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
    assert len(ref.report_id) == 32  # 128-bit ids
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
    assert store.load_html("0" * 16) is None  # neither legacy 8 nor new 32


def test_legacy_8_hex_ids_still_load(tmp_path: Path):
    store = _store(tmp_path)
    reports_dir = tmp_path / "artifacts" / "reports"
    (reports_dir / "deadbeef.json").write_text('{"legacy": true}', encoding="utf-8")
    (reports_dir / "deadbeef.html").write_text("<p>legacy</p>", encoding="utf-8")
    assert store.load_json("deadbeef") == '{"legacy": true}'
    assert store.load_html("deadbeef") == "<p>legacy</p>"


def test_save_never_overwrites_on_id_collision(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    reports_dir = tmp_path / "artifacts" / "reports"
    taken = "ab" * 16
    fresh = "cd" * 16
    (reports_dir / f"{taken}.json").write_text('{"first": 1}', encoding="utf-8")
    (reports_dir / f"{taken}.html").write_text("<p>first</p>", encoding="utf-8")

    ids = iter([taken, fresh])
    monkeypatch.setattr(
        "excel_auditor.storage.reports.secrets.token_hex", lambda n: next(ids)
    )
    ref = store.save(kind="audit", report_json='{"second": 2}', report_html="<p>second</p>")

    assert ref.report_id == fresh  # retried past the collision
    assert store.load_json(taken) == '{"first": 1}'  # untouched
    assert store.load_html(taken) == "<p>first</p>"
    assert store.load_json(fresh) == '{"second": 2}'


def test_save_retries_when_only_html_collides(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    reports_dir = tmp_path / "artifacts" / "reports"
    taken = "ab" * 16
    fresh = "cd" * 16
    (reports_dir / f"{taken}.html").write_text("<p>first</p>", encoding="utf-8")

    ids = iter([taken, fresh])
    monkeypatch.setattr(
        "excel_auditor.storage.reports.secrets.token_hex", lambda n: next(ids)
    )
    ref = store.save(kind="audit", report_json="{}", report_html="<p>second</p>")

    assert ref.report_id == fresh
    assert (reports_dir / f"{taken}.html").read_text(encoding="utf-8") == "<p>first</p>"
    # The half-written json for the colliding id must not linger.
    assert not (reports_dir / f"{taken}.json").exists()
