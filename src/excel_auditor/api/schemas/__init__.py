"""API response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: str
    kind: str
    status: str
    created_at: str
    error: str | None = None
    summary: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
