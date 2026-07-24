"""Upload handling helpers.

Uploads are streamed into an isolated per-request temp directory with a
randomized filename, size-capped, and the whole directory is deleted after
processing. Client filenames are used for display only, never for paths.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from ..config import Settings

_ALLOWED_SUFFIXES = (".xlsx", ".xlsm")
_CHUNK = 1024 * 1024


def sanitize_display_name(filename: str | None) -> str:
    if not filename:
        return "workbook.xlsx"
    name = Path(filename).name  # strip any client-side path components
    return re.sub(r"[^\w.\- ()\[\]]", "_", name)[:120]


def save_upload(upload: UploadFile, dest_dir: Path, settings: Settings) -> Path:
    display = sanitize_display_name(upload.filename)
    suffix = Path(display).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type {suffix or '(none)'}; expected .xlsx or .xlsm.",
        )
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{uuid4().hex}{suffix}"
    size = 0
    with open(path, "wb") as fh:
        while chunk := upload.file.read(_CHUNK):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {settings.max_upload_mb} MB upload limit.",
                )
            fh.write(chunk)
    if size == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    return path
