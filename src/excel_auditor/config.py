"""Application settings.

Plain dataclass + environment variables. Deliberately not a heavier settings
framework: the MVP has a handful of numeric limits and two directories.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ENV_PREFIX = "EXCEL_AUDITOR_"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(_ENV_PREFIX + name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get(_ENV_PREFIX + "DATA_DIR", "./data"))
    )
    artifacts_dir: Path = field(
        default_factory=lambda: Path(os.environ.get(_ENV_PREFIX + "ARTIFACTS_DIR", "./artifacts"))
    )
    base_url: str = field(
        default_factory=lambda: os.environ.get(
            _ENV_PREFIX + "BASE_URL", "http://localhost:8000"
        ).rstrip("/")
    )
    max_upload_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", 25))
    max_decompressed_mb: int = field(default_factory=lambda: _env_int("MAX_DECOMPRESSED_MB", 250))
    max_zip_entries: int = field(default_factory=lambda: _env_int("MAX_ZIP_ENTRIES", 10_000))
    max_zip_ratio: int = field(default_factory=lambda: _env_int("MAX_ZIP_RATIO", 200))
    max_range_cells: int = field(default_factory=lambda: _env_int("MAX_RANGE_CELLS", 10_000))
    web_upload_ttl_seconds: int = field(
        default_factory=lambda: _env_int("WEB_UPLOAD_TTL_SECONDS", 3600)
    )
    log_level: str = field(
        default_factory=lambda: os.environ.get(_ENV_PREFIX + "LOG_LEVEL", "INFO")
    )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_decompressed_bytes(self) -> int:
        return self.max_decompressed_mb * 1024 * 1024

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reports_dir(self) -> Path:
        return self.artifacts_dir / "reports"

    @property
    def web_upload_dir(self) -> Path:
        return self.artifacts_dir / "uploads"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "excel_auditor.db"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.web_upload_dir.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Build settings from the environment. Cheap enough to not need caching."""
    return Settings()
