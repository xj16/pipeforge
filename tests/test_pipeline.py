"""End-to-end tests: run the pipeline and load into a temp SQLite DB."""
from __future__ import annotations

import pandas as pd
import pytest

from pipeforge.config import Config
from pipeforge.pipeline.load import read_table
from pipeforge.pipeline.run import PipelineError, run_pipeline


def test_run_pipeline_loads_all_tables(sqlite_config):
    result = run_pipeline(sqlite_config, load=True)
    for name in ["dim_product", "dim_customer", "dim_date", "fact_sales"]:
        assert result.rows_written[name] > 0
        loaded = read_table(name, sqlite_config)
        assert len(loaded) == result.rows_written[name]


def test_run_pipeline_total_revenue_positive(sqlite_config):
    result = run_pipeline(sqlite_config, load=True)
    assert result.total_revenue > 0


def test_run_pipeline_roundtrip_revenue_matches_db(sqlite_config):
    result = run_pipeline(sqlite_config, load=True)
    fact = read_table("fact_sales", sqlite_config)
    db_total = round(float(fact["revenue"].sum()), 2)
    assert db_total == result.total_revenue


def test_run_without_load_skips_db(sqlite_config):
    result = run_pipeline(sqlite_config, load=False)
    assert result.rows_written == {}
    assert len(result.star.fact_sales) > 0


def test_blocking_check_aborts_run(tmp_path, monkeypatch):
    """A structurally broken extract should abort when fail_on_check is on."""
    import pipeforge.pipeline.run as run_mod

    broken = pd.DataFrame(
        {
            "invoice_no": [None] * 200,  # all-null key -> ERROR check fails
            "stock_code": ["S"] * 200,
            "description": ["d"] * 200,
            "quantity": [1] * 200,
            "unit_price": [1.0] * 200,
            "invoice_date": pd.to_datetime(["2025-01-01"] * 200),
            "customer_id": ["C"] * 200,
            "country": ["UK"] * 200,
        }
    )
    monkeypatch.setattr(run_mod, "extract_orders", lambda _dir: broken)
    config = Config(sqlite_path=tmp_path / "t.db", fail_on_check_error=True)
    with pytest.raises(PipelineError):
        run_pipeline(config, load=True)
