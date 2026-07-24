import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from excel_auditor.api.app import create_app
from excel_auditor.config import Settings


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data", artifacts_dir=tmp_path / "artifacts"
    )
    return TestClient(create_app(settings))


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
