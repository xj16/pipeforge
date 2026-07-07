"""Central configuration for pipeforge.

Everything is driven by a small dataclass so the pipeline can be
reconfigured (e.g. point at Postgres instead of SQLite) without touching
business logic. Values fall back to environment variables so the same
code runs locally, in CI, and inside docker-compose.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Repo layout ---------------------------------------------------------------
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
WAREHOUSE_DIR = DATA_DIR / "warehouse"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


@dataclass
class Config:
    """Runtime configuration for a single pipeline run."""

    # Where the bundled raw CSVs live.
    raw_dir: Path = field(default_factory=lambda: RAW_DIR)

    # Target warehouse. "sqlite" (default, zero-dependency) or "postgres".
    warehouse: str = field(default_factory=lambda: _env("PIPEFORGE_WAREHOUSE", "sqlite"))

    # SQLite database path (used when warehouse == "sqlite").
    sqlite_path: Path = field(
        default_factory=lambda: Path(
            _env("PIPEFORGE_SQLITE_PATH", str(WAREHOUSE_DIR / "pipeforge.db"))
        )
    )

    # Postgres connection string (used when warehouse == "postgres").
    postgres_url: str = field(
        default_factory=lambda: _env(
            "PIPEFORGE_POSTGRES_URL",
            "postgresql+psycopg2://pipeforge:pipeforge@localhost:5432/pipeforge",
        )
    )

    # If True, a failed data-quality check aborts the run. If False, the
    # check result is recorded but the pipeline continues (useful for demos).
    fail_on_check_error: bool = field(
        default_factory=lambda: _env("PIPEFORGE_FAIL_ON_CHECK", "1") == "1"
    )

    # How the load stage writes the warehouse:
    #   "replace" -> drop & rebuild every table (the original, one-shot behaviour)
    #   "append"  -> only load fact rows newer than the stored watermark
    #   "merge"   -> idempotent upsert on natural keys + SCD-2 on dim_customer
    load_mode: str = field(
        default_factory=lambda: _env("PIPEFORGE_LOAD_MODE", "replace").lower()
    )

    def sqlalchemy_url(self) -> str:
        """Return the SQLAlchemy URL for the configured warehouse."""
        if self.warehouse == "postgres":
            return self.postgres_url
        # SQLite: make sure the parent directory exists.
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.sqlite_path}"

    def describe(self) -> str:
        if self.warehouse == "postgres":
            # Never print credentials in logs.
            return "postgres (see PIPEFORGE_POSTGRES_URL)"
        return f"sqlite ({self.sqlite_path})"


def default_config() -> Config:
    return Config()
