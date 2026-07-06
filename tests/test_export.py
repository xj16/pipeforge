"""Tests for the optional (offline) export stubs."""
from __future__ import annotations

from pipeforge.export import export_databricks_parquet, export_snowflake_ddl
from pipeforge.schema.star import build_star_schema


def test_snowflake_ddl_generates_all_tables(raw_df, tmp_path):
    star = build_star_schema(raw_df)
    out = export_snowflake_ddl(star, tmp_path)
    text = out.read_text(encoding="utf-8")
    for table in ["dim_product", "dim_customer", "dim_date", "fact_sales"]:
        assert f"CREATE OR REPLACE TABLE {table}" in text
    assert "NUMBER(38,0)" in text  # integer surrogate keys mapped


def test_databricks_export_writes_files(raw_df, tmp_path):
    star = build_star_schema(raw_df)
    out_dir = export_databricks_parquet(star, tmp_path)
    # Either parquet (if pyarrow present) or csv fallback exists per table.
    for table in ["dim_product", "fact_sales"]:
        matches = list(out_dir.glob(f"{table}.*"))
        assert matches, f"no export file for {table}"
    assert (out_dir / "databricks_load.sql").exists()
