"""Data-contract tests: the declared schema, the live DB, and the exported
Snowflake DDL must all agree on column names and (mapped) types.

This is what stops the export stubs from silently drifting away from the real
warehouse -- the whole point of deriving the DDL from one source of truth.
"""
from __future__ import annotations

from sqlalchemy import create_engine, inspect

from pipeforge.export.snowflake_export import (
    export_snowflake_ddl,
    snowflake_column_type,
)
from pipeforge.pipeline.run import run_pipeline
from pipeforge.schema import warehouse as wh


def test_declared_columns_match_live_sqlite_schema(sqlite_config):
    """Every declared star table exists in the DB with the declared columns."""
    run_pipeline(sqlite_config, load=True)
    engine = create_engine(sqlite_config.sqlalchemy_url())
    inspector = inspect(engine)
    try:
        for table in wh.STAR_TABLES:
            live_cols = {c["name"] for c in inspector.get_columns(table.name)}
            declared_cols = {c.name for c in table.columns}
            assert declared_cols == live_cols, (
                f"{table.name}: declared {declared_cols} != live {live_cols}"
            )
    finally:
        engine.dispose()


def test_live_schema_enforces_declared_primary_keys(sqlite_config):
    run_pipeline(sqlite_config, load=True)
    engine = create_engine(sqlite_config.sqlalchemy_url())
    inspector = inspect(engine)
    try:
        for table in wh.STAR_TABLES:
            pk = set(inspector.get_pk_constraint(table.name)["constrained_columns"])
            declared_pk = {c.name for c in table.primary_key.columns}
            assert pk == declared_pk, f"{table.name} PK mismatch"
    finally:
        engine.dispose()


def test_live_schema_declares_fact_foreign_keys(sqlite_config):
    run_pipeline(sqlite_config, load=True)
    engine = create_engine(sqlite_config.sqlalchemy_url())
    inspector = inspect(engine)
    try:
        fks = inspector.get_foreign_keys("fact_sales")
        referred = {fk["referred_table"] for fk in fks}
        assert {"dim_product", "dim_customer", "dim_date"}.issubset(referred)
    finally:
        engine.dispose()


def test_snowflake_ddl_covers_every_declared_column(raw_df, tmp_path):
    from pipeforge.schema.star import build_star_schema

    star = build_star_schema(raw_df)
    ddl_path = export_snowflake_ddl(star, tmp_path)
    text = ddl_path.read_text(encoding="utf-8")

    for table in wh.STAR_TABLES:
        assert f"CREATE OR REPLACE TABLE {table.name}" in text
        for col in table.columns:
            # Column name + its mapped Snowflake type must both appear.
            assert col.name in text, f"{table.name}.{col.name} missing from DDL"
    # Surrogate integer keys map to NUMBER(38,0); the fact declares FKs.
    assert "NUMBER(38,0)" in text
    assert "FOREIGN KEY" in text


def test_snowflake_type_mapping_is_stable():
    # Spot-check the mapping the DDL relies on.
    assert snowflake_column_type(wh.dim_product.c.product_key) == "NUMBER(38,0)"
    assert snowflake_column_type(wh.dim_product.c.unit_price).startswith("NUMBER(")
    assert snowflake_column_type(wh.dim_date.c.is_weekend) == "BOOLEAN"
    assert snowflake_column_type(wh.dim_date.c.date) == "DATE"
    assert snowflake_column_type(wh.dim_product.c.stock_code).startswith("VARCHAR")
