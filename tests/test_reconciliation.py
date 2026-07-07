"""Tests for post-load reconciliation + run metadata."""
from __future__ import annotations

from pipeforge.pipeline.load import read_table
from pipeforge.pipeline.observability import read_run_history, reconcile
from pipeforge.pipeline.run import run_pipeline


def test_reconciliation_passes_on_clean_load(sqlite_config):
    result = run_pipeline(sqlite_config, load=True)
    names = {r.name for r in result.recon_results}
    assert names == {"recon_no_orphan_fks", "recon_row_counts", "recon_revenue"}
    assert all(r.passed for r in result.recon_results)


def test_reconciliation_detects_orphan_fk(sqlite_config):
    """Manually corrupting the DB with an orphan FK must fail reconciliation."""
    from sqlalchemy import create_engine

    run_pipeline(sqlite_config, load=True)
    # Insert a fact row pointing at a non-existent product_key.
    engine = create_engine(sqlite_config.sqlalchemy_url())
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO fact_sales "
            "(product_key, customer_key, date_key, invoice_no, quantity, unit_price, revenue) "
            "VALUES (99999, 1, 20250101, 'BAD', 1, 1.0, 1.0)"
        )
    engine.dispose()

    results = reconcile(
        sqlite_config, rows_extracted=1, rows_quarantined=0, source_revenue=1.0
    )
    orphan = next(r for r in results if r.name == "recon_no_orphan_fks")
    assert not orphan.passed


def test_run_metadata_persisted(sqlite_config):
    run_pipeline(sqlite_config, load=True)
    run_pipeline(sqlite_config, load=True)
    history = read_run_history(sqlite_config)
    assert len(history) == 2
    row = history.iloc[0]
    assert row["rows_extracted"] > 0
    assert row["load_mode"] == "replace"
    assert float(row["total_revenue"]) > 0
    assert row["git_sha"]  # populated (sha or "unknown")


def test_revenue_reconciles_to_source(sqlite_config):
    result = run_pipeline(sqlite_config, load=True)
    fact = read_table("fact_sales", sqlite_config)
    db_total = round(float(fact["revenue"].sum()), 2)
    assert db_total == result.total_revenue
    revenue_check = next(
        r for r in result.recon_results if r.name == "recon_revenue"
    )
    assert revenue_check.passed
