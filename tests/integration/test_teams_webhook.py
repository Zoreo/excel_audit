"""Teams webhook integration tests.

Fully offline: inbound requests are signed locally and driven through the
TestClient; outbound card posts go through an injected recorder transport.
No network access anywhere.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from excel_auditor.api.app import create_app
from excel_auditor.config import Settings
from excel_auditor.integrations.teams import post_report_card, validate_hmac
from excel_auditor.storage.reports import ReportStore

_KEY = b"unit-test-secret-key-32-bytes!!!"
SECRET_B64 = base64.b64encode(_KEY).decode("ascii")

ADAPTIVE_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"


def _sign(body: bytes) -> str:
    digest = hmac.new(_KEY, body, hashlib.sha256).digest()
    return "HMAC " + base64.b64encode(digest).decode("ascii")


def _settings(root: Path, **overrides) -> Settings:
    return Settings(
        data_dir=root / "data", artifacts_dir=root / "artifacts", **overrides
    )


@pytest.fixture()
def app(tmp_path: Path):
    settings = _settings(
        tmp_path, teams_enabled=True, teams_hmac_secret=SECRET_B64
    )
    return create_app(settings)


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


def _post(
    client: TestClient, text: str, *, authorization: str | None = "sign"
) -> httpx.Response:
    body = json.dumps({"type": "message", "text": text}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if authorization == "sign":
        headers["Authorization"] = _sign(body)
    elif authorization is not None:
        headers["Authorization"] = authorization
    return client.post("/integrations/teams", content=body, headers=headers)


def _store_audit_report(app) -> tuple[str, str]:
    """Persist a minimal audit report; returns (report_id, report_url)."""
    report_json = json.dumps(
        {
            "risk_level": "high",
            "risk_drivers": ["2 critical finding(s)", "5 high-severity finding(s)"],
            "findings": [],
        }
    )
    ref = app.state.report_store.save(
        kind="audit", report_json=report_json, report_html="<html>stub</html>"
    )
    return ref.report_id, ref.url


def _card_of(payload: dict) -> dict:
    assert payload["type"] == "message"
    (attachment,) = payload["attachments"]
    assert attachment["contentType"] == ADAPTIVE_CONTENT_TYPE
    card = attachment["content"]
    assert card["type"] == "AdaptiveCard"
    assert card["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"
    assert card["version"] == "1.4"
    assert card["body"] and all("type" in element for element in card["body"])
    return card


# ------------------------------------------------- acceptance 1: flag off


def test_flag_off_openapi_routes_identical_to_baseline(tmp_path: Path):
    app_off = create_app(_settings(tmp_path / "off"))
    app_on = create_app(
        _settings(tmp_path / "on", teams_enabled=True, teams_hmac_secret=SECRET_B64)
    )
    paths_off = set(app_off.openapi()["paths"])
    paths_on = set(app_on.openapi()["paths"])
    assert "/integrations/teams" not in paths_off
    assert paths_on - paths_off == {"/integrations/teams"}
    # A second flag-off app produces the identical OpenAPI route list:
    # the integration leaves the baseline byte-for-byte unaffected.
    app_off_again = create_app(_settings(tmp_path / "off2"))
    assert set(app_off_again.openapi()["paths"]) == paths_off


def test_flag_off_endpoint_absent(tmp_path: Path):
    client = TestClient(create_app(_settings(tmp_path)))
    body = json.dumps({"type": "message", "text": "help"}).encode()
    response = client.post(
        "/integrations/teams", content=body, headers={"Authorization": _sign(body)}
    )
    assert response.status_code == 404


# ------------------------------------------- acceptance 2: outgoing webhook


def test_status_command_returns_report_card(app, client: TestClient):
    report_id, report_url = _store_audit_report(app)
    response = _post(client, f"<at>Excel Auditor</at> status {report_id}")
    assert response.status_code == 200
    card = _card_of(response.json())
    dumped = json.dumps(card, ensure_ascii=False)
    assert "high" in dumped
    assert report_url in dumped
    assert "audit" in dumped
    assert "2 critical finding(s)" in dumped


def test_invalid_hmac_rejected(app, client: TestClient):
    report_id, _ = _store_audit_report(app)
    text = f"<at>Excel Auditor</at> status {report_id}"

    wrong_key = "HMAC " + base64.b64encode(
        hmac.new(b"wrong-key", json.dumps({"text": text}).encode(), hashlib.sha256).digest()
    ).decode("ascii")
    assert _post(client, text, authorization=wrong_key).status_code == 401
    assert _post(client, text, authorization=None).status_code == 401
    assert _post(client, text, authorization="Bearer whatever").status_code == 401
    assert _post(client, text, authorization="HMAC not-base64!!").status_code == 401


def test_tampered_body_rejected(client: TestClient):
    original = json.dumps({"type": "message", "text": "help"}).encode()
    tampered = json.dumps({"type": "message", "text": "status deadbeef"}).encode()
    response = client.post(
        "/integrations/teams",
        content=tampered,
        headers={
            "Content-Type": "application/json",
            "Authorization": _sign(original),
        },
    )
    assert response.status_code == 401


def test_status_unknown_id_returns_not_found_card(client: TestClient):
    response = _post(client, "<at>Excel Auditor</at> status 0123456789abcdef")
    assert response.status_code == 200
    card = _card_of(response.json())
    dumped = json.dumps(card)
    assert "not found" in dumped.lower()
    assert "0123456789abcdef" in dumped


def test_help_and_unknown_commands_return_help_card(client: TestClient):
    for text in (
        "<at>Excel Auditor</at> help",
        "<at>Excel Auditor</at> do something impossible",
        "",
        "<at>Excel Auditor</at> status",  # status without an id
    ):
        response = _post(client, text)
        assert response.status_code == 200
        dumped = json.dumps(_card_of(response.json()))
        assert "status <report_id>" in dumped


def test_validate_hmac_helper():
    body = b'{"text": "help"}'
    good = _sign(body)
    assert validate_hmac(SECRET_B64, body, good)
    assert not validate_hmac(SECRET_B64, body + b" ", good)
    assert not validate_hmac(SECRET_B64, body, None)
    assert not validate_hmac(SECRET_B64, body, "HMAC ")
    assert not validate_hmac("", body, good)
    assert not validate_hmac("%%%not-base64%%%", body, good)


# ----------------------------------------------- acceptance 3: card poster


class _Summary:
    risk_level = "medium"
    risk_drivers = ["1 high-severity finding"]


def test_post_report_card_sends_exactly_one_post(tmp_path: Path):
    webhook_url = "https://example.webhook.office.com/webhookb2/fake/IncomingWebhook/x/y"
    settings = _settings(tmp_path, teams_incoming_webhook_url=webhook_url)
    ref = ReportStore(settings).save(
        kind="audit", report_json="{}", report_html="<html>stub</html>"
    )

    calls: list[tuple[str, bytes, dict]] = []

    def recorder(url: str, body: bytes, headers) -> int:
        calls.append((url, body, dict(headers)))
        return 200

    status = post_report_card(settings, ref, _Summary(), transport=recorder)

    assert status == 200
    assert len(calls) == 1
    url, body, headers = calls[0]
    assert url == webhook_url
    assert headers["Content-Type"] == "application/json"
    card = _card_of(json.loads(body))
    dumped = json.dumps(card)
    assert "medium" in dumped
    assert "1 high-severity finding" in dumped
    assert ref.url in dumped
    # Schema-valid essentials: an OpenUrl action pointing at the report.
    assert card["actions"][0] == {
        "type": "Action.OpenUrl",
        "title": "Open report",
        "url": ref.url,
    }


def test_post_report_card_requires_configured_url(tmp_path: Path):
    settings = _settings(tmp_path)  # no incoming webhook URL
    ref = ReportStore(settings).save(
        kind="audit", report_json="{}", report_html="<html>stub</html>"
    )
    with pytest.raises(ValueError, match="TEAMS_INCOMING_WEBHOOK_URL"):
        post_report_card(settings, ref, _Summary(), transport=lambda *a: 200)
