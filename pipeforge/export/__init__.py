"""Optional export targets (Snowflake / Databricks).

These are STUBS by design. They generate the SQL DDL and (for Databricks)
Parquet files you would use to load the warehouse into a cloud platform,
but they never require -- or attempt to establish -- a paid connection.
Nothing in the core pipeline depends on this package.
"""
from .snowflake_export import export_snowflake_ddl
from .databricks_export import export_databricks_parquet
from .html_explorer import export_html, render_html

__all__ = [
    "export_snowflake_ddl",
    "export_databricks_parquet",
    "export_html",
    "render_html",
]
