"""Adaptive Card builders for Microsoft Teams.

Pure functions only: (data in) -> (card dict out), no I/O, no service calls.
Cards target Adaptive Cards schema 1.4, the version rendered by Teams.
"""

from __future__ import annotations

from typing import Any

_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
_VERSION = "1.4"

# Accent colour per risk level, mapped to Adaptive Card text colours.
_RISK_COLORS = {
    "minimal": "Good",
    "low": "Good",
    "medium": "Warning",
    "high": "Attention",
    "critical": "Attention",
}


def _card(
    body: list[dict[str, Any]], actions: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "$schema": _SCHEMA,
        "type": "AdaptiveCard",
        "version": _VERSION,
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


def as_teams_message(card: dict[str, Any]) -> dict[str, Any]:
    """Wrap an Adaptive Card in the message envelope Teams webhooks expect."""
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }
        ],
    }


def build_report_card(
    *,
    kind: str,
    risk_level: str,
    drivers: list[str],
    url: str,
    title: str | None = None,
) -> dict[str, Any]:
    """Card summarising a stored report: risk level, drivers and a link."""
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "size": "Medium",
            "weight": "Bolder",
            "text": title or f"Excel Auditor — {kind} report",
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Kind", "value": kind},
                {"title": "Risk level", "value": risk_level},
            ],
        },
    ]
    if drivers:
        body.append(
            {
                "type": "TextBlock",
                "weight": "Bolder",
                "text": "Risk drivers",
                "spacing": "Medium",
            }
        )
        body.extend(
            {"type": "TextBlock", "text": f"- {driver}", "wrap": True}
            for driver in drivers
        )
    body.append(
        {
            "type": "TextBlock",
            "text": f"[Open full report]({url})",
            "wrap": True,
            "color": _RISK_COLORS.get(risk_level, "Default"),
        }
    )
    return _card(body, actions=[{"type": "Action.OpenUrl", "title": "Open report", "url": url}])


def build_help_card() -> dict[str, Any]:
    """Usage card returned for `help` and for any unrecognised command.

    Teams outgoing webhooks cannot receive file attachments, so the webhook
    only offers commands over reports that already exist (uploaded via the
    web UI, CLI or API) - the help text reflects that reality.
    """
    return _card(
        [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": "Excel Auditor — commands",
            },
            {
                "type": "TextBlock",
                "wrap": True,
                "text": (
                    "**status <report_id>** — show the stored report's risk "
                    "summary and link.\n\n**help** — show this message."
                ),
            },
            {
                "type": "TextBlock",
                "wrap": True,
                "isSubtle": True,
                "text": (
                    "Teams outgoing webhooks cannot deliver file attachments; "
                    "upload workbooks via the Excel Auditor web UI, CLI or API "
                    "first, then ask for the report id here."
                ),
            },
        ]
    )


def build_not_found_card(report_id: str) -> dict[str, Any]:
    """Polite card for a `status` command naming an unknown report id."""
    return _card(
        [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "text": "Report not found",
            },
            {
                "type": "TextBlock",
                "wrap": True,
                "text": (
                    f"No stored report matches id `{report_id}`. Double-check "
                    "the id, or generate a new report and try again."
                ),
            },
        ]
    )
