import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from excel_auditor.api.app import create_app
from excel_auditor.config import Settings


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = Settings(data_dir=tmp_path / "data", artifacts_dir=tmp_path / "artifacts")
    return TestClient(create_app(settings))


def _upload(path: Path):
    return ("file", (path.name, open(path, "rb"), "application/octet-stream"))


def test_schema_endpoint(client: TestClient, sales_bg: Path):
    with open(sales_bg, "rb") as fh:
        response = client.post(
            "/api/v1/schema", files={"file": (sales_bg.name, fh, "application/octet-stream")}
        )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["tables"][0]["sheet"] == "Sales"
    column_names = [c["name"] for c in payload["tables"][0]["columns"]]
    assert "Оборот" in column_names

    report = client.get(f"/reports/{payload['report_id']}")
    assert report.status_code == 200
    assert "Оборот" in report.text


def test_structured_query_endpoint(client: TestClient, sales_bg: Path):
    query = {
        "operation": "aggregate",
        "function": "sum",
        "requested_metric": "Оборот",
        "filters": [
            {"column": "__date__", "operator": "year_equals", "value": 2025}
        ],
    }
    with open(sales_bg, "rb") as fh:
        response = client.post(
            "/api/v1/queries",
            files={"file": (sales_bg.name, fh, "application/octet-stream")},
            data={"query": json.dumps(query)},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["result"]["value"] == 628400
    assert payload["report_url"]

    stored = client.get(f"/reports/{payload['report_id']}", params={"format": "json"})
    assert stored.status_code == 200
    assert json.loads(stored.content)["result"]["value"] == 628400


def test_question_endpoint_with_confirmation(client: TestClient, sales_bg: Path):
    ask = {"question": "Какъв е общият оборот за 2025?"}
    with open(sales_bg, "rb") as fh:
        first = client.post(
            "/api/v1/queries",
            files={"file": (sales_bg.name, fh, "application/octet-stream")},
            data=ask,
        )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "needs_confirmation"
    assert len(body["result"]["candidates"]) == 2

    with open(sales_bg, "rb") as fh:
        second = client.post(
            "/api/v1/queries",
            files={"file": (sales_bg.name, fh, "application/octet-stream")},
            data={**ask, "choices": "1"},
        )
    payload = second.json()
    assert payload["status"] in ("verified", "review_recommended")
    assert payload["result"]["value"] == 628400


def test_query_endpoint_requires_input(client: TestClient, sales_bg: Path):
    with open(sales_bg, "rb") as fh:
        response = client.post(
            "/api/v1/queries",
            files={"file": (sales_bg.name, fh, "application/octet-stream")},
        )
    assert response.status_code == 422


def test_unknown_report_404(client: TestClient):
    assert client.get("/reports/deadbeef").status_code == 404
    assert client.get("/reports/%2e%2e%2fx").status_code in (404, 422)


def test_web_pages(client: TestClient, demo_paths):
    for page in ("/", "/audit", "/compare", "/ask"):
        response = client.get(page)
        assert response.status_code == 200, page

    _, v2 = demo_paths
    with open(v2, "rb") as fh:
        response = client.post(
            "/audit",
            files={"file": (v2.name, fh, "application/octet-stream")},
            follow_redirects=False,
        )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/reports/")
    assert client.get(location).status_code == 200


def test_web_ask_flow_with_confirmation(client: TestClient, sales_bg: Path):
    with open(sales_bg, "rb") as fh:
        first = client.post(
            "/ask",
            files={"file": (sales_bg.name, fh, "application/octet-stream")},
            data={"question": "Какъв е общият оборот за 2025?"},
        )
    assert first.status_code == 200
    assert "Confirmation required" in first.text

    # extract the parked-upload token from the rendered form
    import re

    token = re.search(r'name="token" value="([0-9a-f]{16})"', first.text).group(1)
    second = client.post(
        "/ask",
        data={
            "question": "Какъв е общият оборот за 2025?",
            "token": token,
            "choices": "1",
        },
    )
    assert second.status_code == 200
    assert "€628,400" in second.text
