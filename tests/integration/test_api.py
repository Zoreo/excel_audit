import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from excel_auditor.api.app import create_app
from excel_auditor.config import Settings
from excel_auditor.storage.reports import ReportStore


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data", artifacts_dir=tmp_path / "artifacts"
    )
    return TestClient(create_app(settings))


def _store_for(tmp_path: Path) -> ReportStore:
    """A ReportStore over the same artifacts dir the `client` app serves."""
    return ReportStore(
        Settings(data_dir=tmp_path / "data", artifacts_dir=tmp_path / "artifacts")
    )


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_audit_flow(client: TestClient, demo_paths):
    _, v2 = demo_paths
    with open(v2, "rb") as fh:
        response = client.post(
            "/api/v1/audits",
            files={"file": ("model.xlsx", fh, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "completed"
    assert job["summary"]["risk_level"] in {"high", "critical"}

    job_id = job["id"]
    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 200

    report = client.get(f"/api/v1/reports/{job_id}")
    assert report.status_code == 200
    payload = json.loads(report.content)
    assert payload["findings"]

    html = client.get(f"/api/v1/reports/{job_id}", params={"format": "html"})
    assert html.status_code == 200
    assert "Workbook Risk Audit" in html.text


def test_comparison_flow(client: TestClient, demo_paths):
    v1, v2 = demo_paths
    with open(v1, "rb") as f1, open(v2, "rb") as f2:
        response = client.post(
            "/api/v1/comparisons",
            files={
                "old_file": ("v1.xlsx", f1, "application/octet-stream"),
                "new_file": ("v2.xlsx", f2, "application/octet-stream"),
            },
        )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["summary"]["total_cell_changes"] > 0
    assert job["summary"]["review_items"] > 0
    assert job["summary"]["risk_level"] in {"high", "critical"}
    report = client.get(f"/api/v1/reports/{job['id']}").json()
    assert report["summary"]["high_impact_changes"] >= 1
    assert report["review_items"]


def test_rejects_wrong_extension(client: TestClient, tmp_path: Path):
    junk = tmp_path / "notes.txt"
    junk.write_text("hello")
    with open(junk, "rb") as fh:
        response = client.post(
            "/api/v1/audits", files={"file": ("notes.txt", fh, "text/plain")}
        )
    assert response.status_code == 422


def test_rejects_fake_xlsx(client: TestClient, tmp_path: Path):
    junk = tmp_path / "fake.xlsx"
    junk.write_text("this is not a zip")
    with open(junk, "rb") as fh:
        response = client.post(
            "/api/v1/audits", files={"file": ("fake.xlsx", fh, "application/octet-stream")}
        )
    assert response.status_code == 422
    assert "zip" in response.json()["detail"].lower()


def test_unknown_job_is_404(client: TestClient):
    assert client.get("/api/v1/jobs/deadbeef").status_code == 404
    assert client.get("/api/v1/reports/deadbeef").status_code == 404


def test_uploads_are_deleted_after_processing(client: TestClient, demo_paths, tmp_path: Path):
    _, v2 = demo_paths
    with open(v2, "rb") as fh:
        client.post("/api/v1/audits", files={"file": ("m.xlsx", fh, "application/octet-stream")})
    upload_dir = tmp_path / "data" / "uploads"
    assert not any(upload_dir.iterdir())


def _create_audit_job(client: TestClient, demo_paths) -> dict:
    _, v2 = demo_paths
    with open(v2, "rb") as fh:
        response = client.post(
            "/api/v1/audits",
            files={"file": ("model.xlsx", fh, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text
    return response.json()


def test_job_report_served_byte_equal_from_store(
    client: TestClient, demo_paths, tmp_path: Path
):
    job = _create_audit_job(client, demo_paths)
    report_id = job["summary"]["report_id"]
    reports_dir = tmp_path / "artifacts" / "reports"

    via_job = client.get(f"/api/v1/reports/{job['id']}")
    assert via_job.status_code == 200
    assert via_job.content == (reports_dir / f"{report_id}.json").read_bytes()

    via_job_html = client.get(f"/api/v1/reports/{job['id']}", params={"format": "html"})
    assert via_job_html.status_code == 200
    assert via_job_html.content == (reports_dir / f"{report_id}.html").read_bytes()


def test_deleting_stored_files_purges_both_endpoint_families(
    client: TestClient, demo_paths, tmp_path: Path
):
    job = _create_audit_job(client, demo_paths)
    report_id = job["summary"]["report_id"]
    reports_dir = tmp_path / "artifacts" / "reports"

    # Both families serve the report while the files exist.
    assert client.get(f"/api/v1/reports/{job['id']}").status_code == 200
    assert client.get(f"/reports/{report_id}").status_code == 200

    (reports_dir / f"{report_id}.json").unlink()
    (reports_dir / f"{report_id}.html").unlink()

    # The documented purge (delete the artifacts files) must be total.
    assert client.get(f"/api/v1/reports/{job['id']}").status_code == 404
    assert (
        client.get(f"/api/v1/reports/{job['id']}", params={"format": "html"}).status_code
        == 404
    )
    assert client.get(f"/reports/{report_id}").status_code == 404
    assert client.get(f"/reports/{report_id}", params={"format": "json"}).status_code == 404


# ---------------------------------------------------------------- PDF (T13)


def test_stored_pdf_served_via_public_route(client: TestClient, tmp_path: Path):
    ref = _store_for(tmp_path).save(
        kind="audit",
        report_json="{}",
        report_html="<p>x</p>",
        report_pdf=b"%PDF-1.7 stored bytes",
    )
    response = client.get(f"/reports/{ref.report_id}", params={"format": "pdf"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == b"%PDF-1.7 stored bytes"  # byte-equal to the store


def test_pdf_rendered_on_demand_when_not_stored(client: TestClient, tmp_path: Path):
    pytest.importorskip("weasyprint")
    store = _store_for(tmp_path)
    ref = store.save(kind="audit", report_json="{}", report_html="<h1>Report</h1>")
    response = client.get(f"/reports/{ref.report_id}", params={"format": "pdf"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    # GET is side-effect free: the on-demand render is not persisted.
    assert store.load_pdf(ref.report_id) is None


def test_pdf_format_404_for_unknown_or_invalid_report(client: TestClient):
    assert client.get("/reports/deadbeef", params={"format": "pdf"}).status_code == 404
    assert client.get("/reports/..%2fsecret", params={"format": "pdf"}).status_code == 404


def test_pdf_format_422_without_weasyprint(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # weasyprint may be installed here; force the lazy import to fail.
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    ref = _store_for(tmp_path).save(kind="audit", report_json="{}", report_html="<p>x</p>")

    response = client.get(f"/reports/{ref.report_id}", params={"format": "pdf"})
    assert response.status_code == 422
    assert "pip install 'excel-auditor[pdf]'" in response.json()["detail"]

    # HTML/JSON flows are completely unaffected by the missing extra.
    assert client.get(f"/reports/{ref.report_id}").status_code == 200
    assert (
        client.get(f"/reports/{ref.report_id}", params={"format": "json"}).status_code
        == 200
    )


def test_unknown_format_param_is_422(client: TestClient, tmp_path: Path):
    ref = _store_for(tmp_path).save(kind="audit", report_json="{}", report_html="x")
    assert client.get(f"/reports/{ref.report_id}", params={"format": "docx"}).status_code == 422


_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,
    error        TEXT,
    created_at   TEXT NOT NULL,
    source_names TEXT,
    summary_json TEXT,
    report_json  TEXT,
    report_html  TEXT
);
"""


def test_legacy_db_with_blob_columns_still_works(tmp_path: Path):
    import sqlite3

    from excel_auditor.storage.repositories import JobRepository

    settings = Settings(data_dir=tmp_path / "data", artifacts_dir=tmp_path / "artifacts")
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.db_path)
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO jobs (id, kind, status, created_at, source_names, summary_json,"
        " report_json, report_html)"
        " VALUES (?, 'audit', 'completed', ?, ?, ?, ?, ?)",
        (
            "legacyjob",
            "2026-01-01T00:00:00+00:00",
            '["old.xlsx"]',
            '{"risk_level": "high", "report_id": "deadbeef"}',
            '{"legacy": true}',
            "<p>legacy</p>",
        ),
    )
    conn.commit()
    conn.close()

    # The repository opens the legacy DB (CREATE TABLE IF NOT EXISTS is a
    # no-op) and reads the row while ignoring the retired blob columns.
    repo = JobRepository(settings.db_path)
    record = repo.get("legacyjob")
    assert record.status == "completed"
    assert record.summary["report_id"] == "deadbeef"
    assert not hasattr(record, "report_json")

    # New rows insert fine into the legacy table shape.
    new_id = repo.create_completed(
        kind="audit", source_names=["new.xlsx"], summary={"report_id": "cafebabe"}
    )
    assert repo.get(new_id).kind == "audit"

    # The whole app serves the legacy job; the report body 404s because the
    # store files are absent and legacy blobs are ignored by design.
    client = TestClient(create_app(settings))
    assert client.get("/api/v1/jobs/legacyjob").status_code == 200
    assert client.get("/api/v1/reports/legacyjob").status_code == 404
