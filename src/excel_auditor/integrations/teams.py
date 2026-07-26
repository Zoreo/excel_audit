"""Microsoft Teams webhook integration (MVP, decision D11).

Two directions, both plain webhooks - no Microsoft app registration needed:

* Outgoing (Teams -> us): ``POST /integrations/teams`` receives channel
  mentions, validates the HMAC-SHA256 ``Authorization`` header Teams signs
  every request with, and answers exactly two commands: ``status <report_id>``
  and ``help``. Teams outgoing webhooks CANNOT deliver file attachments, so
  no upload-from-chat command exists; users reference reports created via the
  web UI, CLI or API.
* Incoming (us -> Teams): :func:`post_report_card` POSTs an Adaptive Card
  summarising a stored report to the channel's incoming-webhook URL.

No analysis logic lives here (decision D13): stored reports are read through
the ``ReportStore`` public API and summarised as-is. The HTTP transport for
outbound posts is injectable so tests never touch the network.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..config import Settings
from ..storage.reports import ReportRef, ReportStore
from .cards import (
    as_teams_message,
    build_help_card,
    build_not_found_card,
    build_report_card,
)

# (url, body, headers) -> HTTP status code. Injected by tests; the default
# wraps urllib.request. Never called during the test suite.
Transport = Callable[[str, bytes, Mapping[str, str]], int]


class SummaryLike(Protocol):
    """The slice of AuditReport/WorkbookComparison the card needs."""

    @property
    def risk_level(self) -> str: ...

    @property
    def risk_drivers(self) -> list[str]: ...


def _urllib_transport(url: str, body: bytes, headers: Mapping[str, str]) -> int:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    with urllib.request.urlopen(request) as response:
        return int(response.status)


def post_report_card(
    settings: Settings,
    ref: ReportRef,
    summary: SummaryLike,
    *,
    transport: Transport | None = None,
) -> int:
    """POST one Adaptive Card for a stored report to the incoming webhook.

    Returns the HTTP status code reported by the transport.
    """
    url = settings.teams_incoming_webhook_url
    if not url:
        raise ValueError(
            "EXCEL_AUDITOR_TEAMS_INCOMING_WEBHOOK_URL is not configured."
        )
    card = build_report_card(
        kind=ref.kind,
        risk_level=summary.risk_level,
        drivers=list(summary.risk_drivers),
        url=ref.url,
    )
    body = json.dumps(as_teams_message(card)).encode("utf-8")
    send = transport or _urllib_transport
    return send(url, body, {"Content-Type": "application/json"})


# --------------------------------------------------------- outgoing webhook


def validate_hmac(secret_b64: str, raw_body: bytes, authorization: str | None) -> bool:
    """Constant-time check of the Teams outgoing-webhook signature.

    Teams sends ``Authorization: HMAC <base64 digest>`` where the digest is
    HMAC-SHA256 over the raw request body, keyed by the base64-DECODED
    security token shown when the outgoing webhook was created.
    """
    if not secret_b64 or not authorization:
        return False
    scheme, _, received = authorization.partition(" ")
    if scheme != "HMAC" or not received:
        return False
    try:
        key = base64.b64decode(secret_b64, validate=True)
    except (binascii.Error, ValueError):
        return False
    expected = base64.b64encode(hmac.new(key, raw_body, hashlib.sha256).digest()).decode("ascii")
    return hmac.compare_digest(expected, received.strip())


_TAG_RE = re.compile(r"<[^>]+>")


def parse_command(text: str) -> tuple[str, str | None]:
    """Extract (command, argument) from mention text.

    Teams prefixes the message with the bot mention (``<at>Name</at> ...``);
    tags are stripped and the mention name is skipped by keyword search, so
    ``<at>Auditor</at> status abc123`` parses as ``("status", "abc123")``.
    Anything unrecognised maps to ``help``.
    """
    tokens = _TAG_RE.sub(" ", text or "").split()
    lowered = [token.lower() for token in tokens]
    if "status" in lowered:
        index = lowered.index("status")
        argument = tokens[index + 1] if index + 1 < len(tokens) else None
        return "status", argument
    return "help", None


def _kind_of(data: dict[str, Any]) -> str:
    if "old_workbook" in data:
        return "comparison"
    if "findings" in data:
        return "audit"
    if "workbook_schema" in data:
        return "schema"
    if "query" in data or "result" in data:
        return "query"
    return "report"


def _status_card(store: ReportStore, report_id: str | None) -> dict[str, Any]:
    if not report_id:
        return build_help_card()
    raw = store.load_json(report_id)
    if raw is None:
        return build_not_found_card(report_id)
    data = json.loads(raw)
    return build_report_card(
        kind=_kind_of(data),
        risk_level=str(data.get("risk_level", "n/a")),
        drivers=[str(d) for d in data.get("risk_drivers") or []],
        url=store.url_for(report_id),
    )


router = APIRouter()


@router.post("/integrations/teams")
async def teams_outgoing_webhook(request: Request) -> JSONResponse:
    """Handle a Teams outgoing-webhook mention (``status <id>`` / ``help``)."""
    raw_body = await request.body()
    settings: Settings = request.app.state.settings
    if not validate_hmac(
        settings.teams_hmac_secret, raw_body, request.headers.get("Authorization")
    ):
        return JSONResponse(
            status_code=401, content={"detail": "Invalid or missing HMAC signature."}
        )

    try:
        payload = json.loads(raw_body)
        text = str(payload.get("text", "")) if isinstance(payload, dict) else ""
    except (json.JSONDecodeError, UnicodeDecodeError):
        text = ""

    command, argument = parse_command(text)
    store: ReportStore = request.app.state.report_store
    card = _status_card(store, argument) if command == "status" else build_help_card()
    return JSONResponse(status_code=200, content=as_teams_message(card))
