"""The explicit warehouse schema: one source of truth for every table.

Instead of letting ``DataFrame.to_sql`` infer column types, we declare the
star schema as SQLAlchemy Core :class:`~sqlalchemy.Table` objects with real
types, primary keys on the surrogate keys, foreign keys from the fact to the
dimensions, ``NOT NULL`` on the key columns, and an index on ``date_key``.

Everything downstream derives from this module:

* the load stage creates the tables from this metadata, then bulk-inserts,
  so the storage layer enforces referential integrity (a bad transform that
  produced an orphan FK or a null key would be rejected by the database);
* the Snowflake DDL generator maps these declared columns (not pandas-inferred
  dtypes), so the export can never silently drift from the live warehouse;
* the reconciliation checks and the HTML explorer read the same table names.

The natural (business) key of the fact grain is
``(invoice_no, stock_code, date_key)``; it is declared ``UNIQUE`` so the
idempotent ``merge`` load mode can upsert on it.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)

# A dedicated MetaData object so we never touch unrelated tables in the DB.
metadata = MetaData()

# --- Dimensions ------------------------------------------------------------

dim_product = Table(
    "dim_product",
    metadata,
    Column("product_key", Integer, primary_key=True),
    Column("stock_code", String(32), nullable=False, unique=True),
    Column("description", String(256)),
    Column("category", String(64), nullable=False),
    Column("unit_price", Numeric(12, 2), nullable=False),
)

dim_customer = Table(
    "dim_customer",
    metadata,
    Column("customer_key", Integer, primary_key=True),
    Column("customer_id", String(32), nullable=False),
    Column("country", String(64), nullable=False),
    # SCD-2 versioning columns. For the default (type-1) build these carry a
    # single open version per customer; the SCD-2 build closes/opens rows.
    Column("effective_from", Date, nullable=False),
    Column("effective_to", Date, nullable=True),
    Column("is_current", Boolean, nullable=False),
    # A customer_id may appear multiple times across versions, but only one
    # (customer_id, effective_from) pair may exist.
    UniqueConstraint("customer_id", "effective_from", name="uq_customer_version"),
)

dim_date = Table(
    "dim_date",
    metadata,
    Column("date_key", Integer, primary_key=True),  # yyyymmdd
    Column("date", Date, nullable=False),
    Column("year", Integer, nullable=False),
    Column("quarter", Integer, nullable=False),
    Column("month", Integer, nullable=False),
    Column("day", Integer, nullable=False),
    Column("weekday", String(16), nullable=False),
    Column("is_weekend", Boolean, nullable=False),
)

# --- Fact ------------------------------------------------------------------

fact_sales = Table(
    "fact_sales",
    metadata,
    Column("sale_id", Integer, primary_key=True),
    Column(
        "product_key",
        Integer,
        ForeignKey("dim_product.product_key"),
        nullable=False,
    ),
    Column(
        "customer_key",
        Integer,
        ForeignKey("dim_customer.customer_key"),
        nullable=False,
    ),
    Column(
        "date_key",
        Integer,
        ForeignKey("dim_date.date_key"),
        nullable=False,
    ),
    Column("invoice_no", String(32), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(12, 2), nullable=False),
    Column("revenue", Numeric(14, 2), nullable=False),
    # Natural key of the grain: one row per invoice line. ``stock_code`` is
    # represented on the fact by its resolved ``product_key``, so the grain is
    # (invoice_no, product_key, date_key). Declared UNIQUE so the idempotent
    # MERGE/upsert can target it and the DB blocks accidental double-loads.
    UniqueConstraint(
        "invoice_no", "product_key", "date_key", name="uq_fact_natural_key"
    ),
    Index("ix_fact_date_key", "date_key"),
    Index("ix_fact_product_key", "product_key"),
    Index("ix_fact_customer_key", "customer_key"),
)

# --- Quarantine + run metadata (operational, not part of the star) ---------

quarantine = Table(
    "quarantine",
    metadata,
    Column("invoice_no", String(32)),
    Column("stock_code", String(32)),
    Column("description", String(256)),
    Column("quantity", Integer),
    Column("unit_price", Numeric(12, 2)),
    Column("invoice_date", Date),
    Column("customer_id", String(32)),
    Column("country", String(64)),
    Column("quarantine_reason", String(64), nullable=False),
)

pipeline_runs = Table(
    "pipeline_runs",
    metadata,
    Column("run_id", String(36), primary_key=True),
    Column("started_at", String(32), nullable=False),
    Column("finished_at", String(32), nullable=False),
    Column("load_mode", String(16), nullable=False),
    Column("rows_extracted", Integer, nullable=False),
    Column("rows_loaded", Integer, nullable=False),
    Column("rows_quarantined", Integer, nullable=False),
    Column("total_revenue", Numeric(16, 2), nullable=False),
    Column("git_sha", String(40), nullable=False),
)


# The four analytical tables, in FK-safe creation order.
STAR_TABLES: tuple[Table, ...] = (dim_product, dim_customer, dim_date, fact_sales)

# Natural-key columns per table, used by the merge/upsert load mode.
NATURAL_KEYS: dict[str, tuple[str, ...]] = {
    "dim_product": ("stock_code",),
    "dim_customer": ("customer_id", "effective_from"),
    "dim_date": ("date_key",),
    "fact_sales": ("invoice_no", "product_key", "date_key"),
}


def table_by_name(name: str) -> Table:
    """Return the declared :class:`Table` for ``name`` (raises if unknown)."""
    return metadata.tables[name]
