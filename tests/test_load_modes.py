"""Flagship tests for the incremental / idempotent load engine.

These cover the hardest, most-advertised subsystem: the three load modes,
watermark-driven append, idempotency of merge, and Type-2 SCD on
dim_customer. They run against a real (temp) SQLite warehouse so the storage
layer's constraints are exercised too.
"""
from __future__ import annotations

import pandas as pd
import pytest

from pipeforge.config import Config
from pipeforge.pipeline.load import load_star_schema, read_table
from pipeforge.pipeline.run import run_pipeline
from pipeforge.schema.star import build_star_schema


def _raw(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["quantity"] = df["quantity"].astype("Int64")
    df["unit_price"] = df["unit_price"].astype(float)
    df["invoice_date"] = pd.to_datetime(df["invoice_date"])
    return df


def _row(invoice, stock, cust, country, date, qty=1, price=10.0, desc="X"):
    return {
        "invoice_no": invoice,
        "stock_code": stock,
        "description": desc,
        "quantity": qty,
        "unit_price": price,
        "invoice_date": date,
        "customer_id": cust,
        "country": country,
    }


# --- replace mode ----------------------------------------------------------
def test_replace_mode_rebuilds_each_run(tmp_path):
    cfg = Config(sqlite_path=tmp_path / "wh.db", load_mode="replace")
    run_pipeline(cfg, load=True)
    first = len(read_table("fact_sales", cfg))
    run_pipeline(cfg, load=True)
    second = len(read_table("fact_sales", cfg))
    assert first == second  # replace is deterministic, not additive


# --- merge mode idempotency ------------------------------------------------
def test_merge_mode_is_idempotent(tmp_path):
    cfg = Config(sqlite_path=tmp_path / "wh.db", load_mode="merge")
    run_pipeline(cfg, load=True)
    counts_1 = {t: len(read_table(t, cfg)) for t in ("fact_sales", "dim_customer")}
    # Re-running the same data must not duplicate anything.
    run_pipeline(cfg, load=True)
    counts_2 = {t: len(read_table(t, cfg)) for t in ("fact_sales", "dim_customer")}
    assert counts_1 == counts_2


def test_merge_reconciliation_passes(tmp_path):
    cfg = Config(sqlite_path=tmp_path / "wh.db", load_mode="merge")
    result = run_pipeline(cfg, load=True)
    assert result.recon_results, "reconciliation should run in merge mode"
    assert all(r.passed for r in result.recon_results)


# --- append mode + watermark ----------------------------------------------
def test_append_mode_only_loads_new_dates(tmp_path):
    cfg = Config(sqlite_path=tmp_path / "wh.db", load_mode="append")

    # Seed with early dates.
    seed = _raw(
        [
            _row("INV1", "SKU-001", "C-1", "UK", "2025-01-01"),
            _row("INV2", "SKU-002", "C-2", "DE", "2025-01-02"),
        ]
    )
    load_star_schema(build_star_schema(seed), cfg)
    assert len(read_table("fact_sales", cfg)) == 2

    # A batch that mixes an already-seen date and a new, later date.
    batch = _raw(
        [
            _row("INV1", "SKU-001", "C-1", "UK", "2025-01-01"),  # <= watermark
            _row("INV3", "SKU-003", "C-3", "FR", "2025-02-01"),  # > watermark
        ]
    )
    load_star_schema(build_star_schema(batch), cfg)
    fact = read_table("fact_sales", cfg)
    # Only the new-date row is added; the old one is not re-inserted.
    assert len(fact) == 3
    assert 20250201 in set(fact["date_key"])


# --- SCD-2 on dim_customer -------------------------------------------------
def test_scd2_versions_customer_on_country_change(tmp_path):
    cfg = Config(sqlite_path=tmp_path / "wh.db", load_mode="merge")

    load_star_schema(
        build_star_schema(_raw([_row("INV1", "SKU-001", "C-1", "Germany", "2025-01-01")])),
        cfg,
    )
    dc = read_table("dim_customer", cfg)
    assert len(dc[dc["customer_id"] == "C-1"]) == 1
    assert bool(dc.iloc[0]["is_current"]) is True

    # Same customer, new country -> a new version, old one closed.
    load_star_schema(
        build_star_schema(_raw([_row("INV2", "SKU-001", "C-1", "Austria", "2025-02-01")])),
        cfg,
    )
    dc = read_table("dim_customer", cfg)
    versions = dc[dc["customer_id"] == "C-1"].sort_values("customer_key")
    assert len(versions) == 2
    old, new = versions.iloc[0], versions.iloc[1]
    assert not bool(old["is_current"]) and pd.notna(old["effective_to"])
    assert bool(new["is_current"]) and new["country"] == "Austria"
    assert old["country"] == "Germany"


def test_scd2_no_change_is_noop(tmp_path):
    cfg = Config(sqlite_path=tmp_path / "wh.db", load_mode="merge")
    raw = _raw([_row("INV1", "SKU-001", "C-1", "Germany", "2025-01-01")])
    load_star_schema(build_star_schema(raw), cfg)
    load_star_schema(build_star_schema(raw), cfg)  # identical re-run
    dc = read_table("dim_customer", cfg)
    assert len(dc[dc["customer_id"] == "C-1"]) == 1  # still one version


def test_fact_points_at_current_customer_after_scd2(tmp_path):
    cfg = Config(sqlite_path=tmp_path / "wh.db", load_mode="merge")
    load_star_schema(
        build_star_schema(_raw([_row("INV1", "SKU-001", "C-1", "Germany", "2025-01-01")])),
        cfg,
    )
    load_star_schema(
        build_star_schema(_raw([_row("INV2", "SKU-001", "C-1", "Austria", "2025-02-01")])),
        cfg,
    )
    fact = read_table("fact_sales", cfg)
    dc = read_table("dim_customer", cfg)
    current_key = int(dc[(dc["customer_id"] == "C-1") & (dc["is_current"] == 1)]["customer_key"].iloc[0])
    # The newest fact row resolves to the current (Austria) customer version.
    newest = fact.sort_values("date_key").iloc[-1]
    assert int(newest["customer_key"]) == current_key


def test_unknown_load_mode_raises(tmp_path):
    cfg = Config(sqlite_path=tmp_path / "wh.db", load_mode="teleport")
    star = build_star_schema(_raw([_row("INV1", "SKU-001", "C-1", "UK", "2025-01-01")]))
    with pytest.raises(ValueError, match="PIPEFORGE_LOAD_MODE"):
        load_star_schema(star, cfg)
