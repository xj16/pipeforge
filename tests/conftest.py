"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from pipeforge.config import Config
from pipeforge.generate_dataset import main as generate_dataset
from pipeforge.pipeline.extract import extract_orders


@pytest.fixture(scope="session")
def dataset_dir() -> Path:
    """Ensure the bundled dataset exists; return its raw dir."""
    path = generate_dataset()
    return path.parent


@pytest.fixture()
def raw_df(dataset_dir):
    return extract_orders(dataset_dir)


@pytest.fixture()
def sqlite_config(tmp_path) -> Config:
    """A Config pointing at a throwaway SQLite file in a temp dir."""
    return Config(sqlite_path=tmp_path / "test.db", fail_on_check_error=True)
