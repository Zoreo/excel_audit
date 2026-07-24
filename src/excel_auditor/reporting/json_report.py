"""Machine-readable JSON reports."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


def to_json(report: BaseModel) -> str:
    return report.model_dump_json(indent=2)


def write_json(report: BaseModel, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(report), encoding="utf-8")
    return path
