"""Web /ask upload lifecycle (SECURITY-001): parked uploads must be deleted
on every exit path except the needs-confirmation round trip, and a TTL sweep
removes abandoned leftovers at startup and on each submission."""

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from excel_auditor.api.app import create_app
from excel_auditor.config import Settings


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", artifacts_dir=tmp_path / "artifacts")


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)


def _web_uploads(settings: Settings) -> list[Path]:
    return sorted(settings.web_upload_dir.iterdir())


def _age(directory: Path, seconds: float) -> None:
    stamp = time.time() - seconds
    os.utime(directory, (stamp, stamp))


CONFIRM_QUESTION = "Какъв е общият оборот за 2025?"


# ------------------------------------------------------------- cleanup paths


def test_invalid_upload_leaves_nothing_behind(client: TestClient, settings: Settings):
    """Regression for the proven 422 leak: a corrupt workbook fails pre-parse
    (inspect_schema) and must not leave the parked copy behind."""
    response = client.post(
        "/ask",
        files={"file": ("fake.xlsx", b"this is not a zip", "application/octet-stream")},
        data={"question": "What was total revenue in 2025?"},
    )
    assert response.status_code == 422
    assert _web_uploads(settings) == []


def test_rejected_extension_leaves_nothing_behind(client: TestClient, settings: Settings):
    """save_upload itself refuses the file after creating the directory."""
    response = client.post(
        "/ask",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"question": "What was total revenue in 2025?"},
    )
    assert response.status_code == 422
    assert _web_uploads(settings) == []


def test_unsupported_question_leaves_nothing_behind(
    client: TestClient, settings: Settings, sales_bg_simple: Path
):
    with open(sales_bg_simple, "rb") as fh:
        response = client.post(
            "/ask",
            files={"file": (sales_bg_simple.name, fh, "application/octet-stream")},
            data={"question": "Tell me everything interesting about this company."},
        )
    assert response.status_code == 200
    assert "error" in response.text
    assert _web_uploads(settings) == []


def test_answer_query_exception_leaves_nothing_behind(
    client: TestClient, settings: Settings, sales_bg_simple: Path, monkeypatch
):
    def boom(*args, **kwargs):
        raise RuntimeError("mid-flow failure")

    monkeypatch.setattr("excel_auditor.web.routes.answer_query", boom)
    with open(sales_bg_simple, "rb") as fh:
        response = client.post(
            "/ask",
            files={"file": (sales_bg_simple.name, fh, "application/octet-stream")},
            data={"question": "What was total revenue in 2025?"},
        )
    assert response.status_code == 500
    assert _web_uploads(settings) == []


def test_happy_path_answers_and_cleans_up(
    client: TestClient, settings: Settings, sales_bg_simple: Path
):
    with open(sales_bg_simple, "rb") as fh:
        response = client.post(
            "/ask",
            files={"file": (sales_bg_simple.name, fh, "application/octet-stream")},
            data={"question": "What was total revenue in 2025?"},
        )
    assert response.status_code == 200
    assert "628" in response.text  # 628,400 total
    assert _web_uploads(settings) == []


# ------------------------------------------------------- confirmation flow


def test_confirmation_keeps_parked_file_then_deletes_it(
    client: TestClient, settings: Settings, sales_bg: Path
):
    with open(sales_bg, "rb") as fh:
        first = client.post(
            "/ask",
            files={"file": (sales_bg.name, fh, "application/octet-stream")},
            data={"question": CONFIRM_QUESTION},
        )
    assert first.status_code == 200
    assert "Confirmation required" in first.text

    parked = _web_uploads(settings)
    assert len(parked) == 1  # the parked copy survives the round trip
    token = parked[0].name
    assert token in first.text

    second = client.post(
        "/ask",
        data={"question": CONFIRM_QUESTION, "token": token, "choices": "1"},
    )
    assert second.status_code == 200
    assert "628" in second.text  # gross 2025 total 628,400
    assert _web_uploads(settings) == []  # deleted after the answer


def test_expired_token_shows_error(client: TestClient, settings: Settings):
    response = client.post(
        "/ask",
        data={"question": CONFIRM_QUESTION, "token": "0" * 16, "choices": "1"},
    )
    assert response.status_code == 200
    assert "Upload expired" in response.text
    assert _web_uploads(settings) == []


# ----------------------------------------------------------------- TTL sweep


def test_submission_sweeps_expired_but_not_fresh_uploads(
    client: TestClient, settings: Settings
):
    expired = settings.web_upload_dir / "aaaaaaaaaaaaaaaa"
    expired.mkdir(parents=True)
    (expired / "old.xlsx").write_bytes(b"stale")
    _age(expired, settings.web_upload_ttl_seconds + 60)

    fresh = settings.web_upload_dir / "bbbbbbbbbbbbbbbb"
    fresh.mkdir(parents=True)
    (fresh / "recent.xlsx").write_bytes(b"recent")

    # Any /ask submission sweeps opportunistically (here: the no-file branch).
    response = client.post("/ask", data={"question": "anything"})
    assert response.status_code == 200

    assert not expired.exists()
    assert fresh.is_dir()  # younger than the TTL: never swept mid-flow


def test_startup_sweep_removes_pre_aged_uploads(settings: Settings):
    settings.ensure_dirs()
    stale = settings.web_upload_dir / "cccccccccccccccc"
    stale.mkdir(parents=True)
    (stale / "leak.xlsx").write_bytes(b"leftover")
    _age(stale, settings.web_upload_ttl_seconds + 60)

    fresh = settings.web_upload_dir / "dddddddddddddddd"
    fresh.mkdir(parents=True)

    create_app(settings)  # startup sweep runs in the app factory

    assert not stale.exists()
    assert fresh.is_dir()
