"""Smoke tests for the CLI command surface."""
from __future__ import annotations

import pytest

from pipeforge import cli


@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    """Point the CLI's default_config at a temp SQLite warehouse."""
    db = tmp_path / "cli.db"
    monkeypatch.setenv("PIPEFORGE_SQLITE_PATH", str(db))
    monkeypatch.setenv("PIPEFORGE_LOAD_MODE", "replace")
    return db


def test_cli_run_then_report(cli_env, capsys):
    assert cli.main(["run"]) == 0
    out = capsys.readouterr().out
    assert "Total revenue" in out
    assert "Post-load reconciliation" in out

    assert cli.main(["report"]) == 0
    out = capsys.readouterr().out
    assert "revenue by category" in out


def test_cli_check(cli_env, capsys):
    rc = cli.main(["check"])
    assert rc == 0  # bundled dirt is all WARNING-level -> non-blocking
    out = capsys.readouterr().out
    assert "row_count_at_least" in out


def test_cli_export_stubs(cli_env, tmp_path, capsys):
    out_dir = tmp_path / "exp"
    assert cli.main(["export", "--out", str(out_dir)]) == 0
    assert (out_dir / "snowflake_schema.sql").exists()
    assert (out_dir / "databricks_load.sql").exists()


def test_cli_export_html(cli_env, tmp_path, capsys):
    out_dir = tmp_path / "site"
    assert cli.main(["export", "--html", "--out", str(out_dir)]) == 0
    index = out_dir / "index.html"
    assert index.exists()
    assert "<!doctype html>" in index.read_text(encoding="utf-8").lower()


def test_cli_report_without_run_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PIPEFORGE_SQLITE_PATH", str(tmp_path / "empty.db"))
    rc = cli.main(["report"])
    assert rc == 1  # nothing loaded yet
