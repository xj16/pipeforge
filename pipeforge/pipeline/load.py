"""Load stage: write the star-schema tables into the warehouse.

Uses SQLAlchemy so the same code targets SQLite (default) or Postgres.
SQLAlchemy + pandas are the only hard requirements; the Postgres driver
(psycopg2) is optional and only imported by SQLAlchemy when a postgres URL
is actually used.
"""
from __future__ import annotations

from ..config import Config
from ..schema.star import StarSchema


def load_star_schema(star: StarSchema, config: Config) -> dict[str, int]:
    """Write all warehouse tables (and quarantine) to the configured DB.

    Returns a mapping of table name -> rows written.
    """
    from sqlalchemy import create_engine  # imported lazily so import is cheap

    engine = create_engine(config.sqlalchemy_url())
    written: dict[str, int] = {}

    tables = dict(star.tables())
    tables["quarantine"] = star.quarantine

    with engine.begin() as conn:
        for name, df in tables.items():
            df.to_sql(name, conn, if_exists="replace", index=False)
            written[name] = len(df)

    engine.dispose()
    return written


def read_table(table: str, config: Config):
    """Convenience reader used by tests and the CLI report."""
    import pandas as pd
    from sqlalchemy import create_engine

    engine = create_engine(config.sqlalchemy_url())
    try:
        return pd.read_sql_table(table, engine)
    finally:
        engine.dispose()
