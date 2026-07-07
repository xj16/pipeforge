"""Load stage: write the star schema into the warehouse.

The load stage no longer relies on ``DataFrame.to_sql`` type inference. It
creates the tables from the explicit, typed schema in
:mod:`pipeforge.schema.warehouse` (real PKs, FKs, NOT NULL, indexes) and then
bulk-inserts through SQLAlchemy Core, so the storage layer enforces
referential integrity for SQLite and Postgres alike.

Three load modes (``PIPEFORGE_LOAD_MODE`` / ``Config.load_mode``):

``replace`` (default)
    Drop and recreate every table, then insert. The original one-shot
    behaviour -- deterministic and simple.

``append``
    Keep existing rows; insert only fact rows strictly newer than the stored
    high-water-mark on ``date_key``. Dimensions are upserted (new members
    added, existing ones left untouched). Idempotent for already-seen dates.

``merge``
    Fully idempotent upsert on natural keys for every table, plus a Type-2
    slowly-changing dimension on ``dim_customer``: when a customer's country
    changes between runs, the current row is closed (``effective_to`` set,
    ``is_current`` cleared) and a new versioned row is opened.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, Table, create_engine, func, select

from ..config import Config
from ..schema import warehouse as wh
from ..schema.star import StarSchema

VALID_LOAD_MODES = ("replace", "append", "merge")


# --------------------------------------------------------------------------
# Engine + DDL helpers
# --------------------------------------------------------------------------
def _make_engine(config: Config) -> Engine:
    engine = create_engine(config.sqlalchemy_url())
    if engine.dialect.name == "sqlite":
        # Enforce declared foreign keys on SQLite (off by default).
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def ensure_schema(engine: Engine) -> None:
    """Create every declared table if it does not already exist."""
    wh.metadata.create_all(engine)


def _records(df: pd.DataFrame) -> list[dict]:
    """Convert a frame to insert-ready dicts, normalising pandas NA/NaT."""
    safe = df.astype(object).where(pd.notna(df), None)
    return safe.to_dict(orient="records")


# --------------------------------------------------------------------------
# Dialect-aware upsert (INSERT .. ON CONFLICT for SQLite & Postgres)
# --------------------------------------------------------------------------
def _upsert(
    conn,
    table: Table,
    rows: list[dict],
    conflict_cols: tuple[str, ...],
    *,
    drop_surrogate: bool = False,
) -> int:
    """Dialect-aware INSERT .. ON CONFLICT upsert on ``conflict_cols``.

    When ``drop_surrogate`` is set, the table's autoincrement primary key is
    stripped from the incoming rows so it never collides with a persisted key:
    existing rows keep their surrogate, new rows get a fresh one from the DB.
    Use this for dimensions whose PK is separate from their natural key.
    """
    if not rows:
        return 0
    pk_cols = {c.name for c in table.primary_key.columns}
    if drop_surrogate:
        rows = [{k: v for k, v in r.items() if k not in pk_cols} for r in rows]
    # Update only columns actually supplied (e.g. fact rows omit the
    # autoincrement sale_id), never the conflict-key columns nor the primary
    # key (rewriting the PK to excluded's value defeats the upsert).
    present = set(rows[0].keys())
    updatable = [
        c for c in present if c not in conflict_cols and c not in pk_cols
    ]

    dialect = conn.engine.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_cols),
            set_={name: stmt.excluded[name] for name in updatable},
        )
    else:  # sqlite (and any other) -> sqlite ON CONFLICT
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_cols),
            set_={name: getattr(stmt.excluded, name) for name in updatable},
        )
    conn.execute(stmt)
    return len(rows)


# --------------------------------------------------------------------------
# Load modes
# --------------------------------------------------------------------------
def _load_replace(conn, star: StarSchema) -> dict[str, int]:
    """Drop + recreate the analytical tables, then insert everything."""
    # Recreate only the star tables (+ quarantine); leave pipeline_runs alone.
    to_reset = list(wh.STAR_TABLES) + [wh.quarantine]
    wh.metadata.drop_all(conn, tables=to_reset)
    wh.metadata.create_all(conn, tables=to_reset)

    written: dict[str, int] = {}
    for table in wh.STAR_TABLES:
        df = _frame_for(star, table.name)
        rows = _records(df)
        if rows:
            conn.execute(table.insert(), rows)
        written[table.name] = len(rows)

    q_rows = _records(star.quarantine)
    if q_rows:
        conn.execute(wh.quarantine.insert(), q_rows)
    written["quarantine"] = len(q_rows)
    return written


def _current_watermark(conn) -> int:
    """Highest ``date_key`` already in ``fact_sales`` (0 if empty/absent)."""
    result = conn.execute(select(func.max(wh.fact_sales.c.date_key))).scalar()
    return int(result) if result is not None else 0


def _load_append(conn, star: StarSchema) -> dict[str, int]:
    """Upsert dimensions; insert only fact rows past the watermark."""
    written: dict[str, int] = {}

    # Dimensions: upsert so new members appear, existing ones stay put. The
    # product/customer surrogate keys are dropped so a re-run keeps whatever
    # key was persisted; dim_date's key IS its natural key so it is supplied.
    written["dim_product"] = _upsert(
        conn, wh.dim_product, _records(star.dim_product),
        wh.NATURAL_KEYS["dim_product"], drop_surrogate=True,
    )
    written["dim_customer"] = _upsert(
        conn, wh.dim_customer, _records(star.dim_customer),
        wh.NATURAL_KEYS["dim_customer"], drop_surrogate=True,
    )
    written["dim_date"] = _upsert(
        conn, wh.dim_date, _records(star.dim_date), wh.NATURAL_KEYS["dim_date"],
    )

    # Fact: only rows strictly newer than the stored high-water-mark.
    watermark = _current_watermark(conn)
    fact_db = _reindex_fact(conn, star)
    new_fact = fact_db[fact_db["date_key"] > watermark]
    written["fact_sales"] = _upsert(
        conn, wh.fact_sales, _records(new_fact), wh.NATURAL_KEYS["fact_sales"],
    )

    written["quarantine"] = _upsert_quarantine(conn, star.quarantine)
    return written


def _load_merge(conn, star: StarSchema) -> dict[str, int]:
    """Idempotent upsert everywhere + SCD-2 on dim_customer."""
    written: dict[str, int] = {}

    written["dim_product"] = _upsert(
        conn, wh.dim_product, _records(star.dim_product),
        wh.NATURAL_KEYS["dim_product"], drop_surrogate=True,
    )
    written["dim_customer"] = _apply_scd2_customer(conn, star.dim_customer)
    written["dim_date"] = _upsert(
        conn, wh.dim_date, _records(star.dim_date), wh.NATURAL_KEYS["dim_date"],
    )

    fact_db = _reindex_fact(conn, star)
    written["fact_sales"] = _upsert(
        conn, wh.fact_sales, _records(fact_db), wh.NATURAL_KEYS["fact_sales"],
    )
    written["quarantine"] = _upsert_quarantine(conn, star.quarantine)
    return written


def _upsert_quarantine(conn, quarantine: pd.DataFrame) -> int:
    """Quarantine has no natural key, so replace it wholesale (point-in-time)."""
    conn.execute(wh.quarantine.delete())
    rows = _records(quarantine)
    if rows:
        conn.execute(wh.quarantine.insert(), rows)
    return len(rows)


# --------------------------------------------------------------------------
# SCD-2 for dim_customer
# --------------------------------------------------------------------------
def _apply_scd2_customer(conn, incoming: pd.DataFrame) -> int:
    """Close changed customer versions and open new ones (Type-2 SCD).

    For each incoming customer:
      * no current row      -> insert as the first open version;
      * country unchanged   -> no-op;
      * country changed     -> close the old row (effective_to = today,
                               is_current = False) and insert a new open
                               version with a fresh surrogate key.
    """
    from datetime import date

    from ..schema.star import SCD_EPOCH

    today = date.today()
    epoch = SCD_EPOCH.date()
    tbl = wh.dim_customer

    existing = pd.read_sql(
        select(tbl).where(tbl.c.is_current == True), conn  # noqa: E712
    )
    existing_by_id = {row["customer_id"]: row for _, row in existing.iterrows()}

    max_key = conn.execute(select(func.max(tbl.c.customer_key))).scalar() or 0
    next_key = int(max_key) + 1

    changed = 0
    for _, new in incoming.iterrows():
        cid = new["customer_id"]
        old = existing_by_id.get(cid)
        if old is None:
            # Brand-new customer: open the first version at the SCD epoch so a
            # same-day country change can open a second version at `today`
            # without colliding on (customer_id, effective_from).
            conn.execute(
                tbl.insert().values(
                    customer_key=next_key,
                    customer_id=cid,
                    country=new["country"],
                    effective_from=epoch,
                    effective_to=None,
                    is_current=True,
                )
            )
            next_key += 1
            changed += 1
            continue
        if old["country"] == new["country"]:
            continue  # unchanged, nothing to do
        # Country changed -> close old, open new version.
        conn.execute(
            tbl.update()
            .where(tbl.c.customer_key == int(old["customer_key"]))
            .values(effective_to=today, is_current=False)
        )
        conn.execute(
            tbl.insert().values(
                customer_key=next_key,
                customer_id=cid,
                country=new["country"],
                effective_from=today,
                effective_to=None,
                is_current=True,
            )
        )
        next_key += 1
        changed += 1
    return changed


# --------------------------------------------------------------------------
# Fact key re-resolution against the live dimensions
# --------------------------------------------------------------------------
def _reindex_fact(conn, star: StarSchema) -> pd.DataFrame:
    """Re-point the fact's FKs at the surrogate keys actually stored in the DB.

    The transform assigns product/customer keys 1..N in isolation; in
    incremental modes those may differ from the keys already persisted (e.g. a
    later run sees products in a different order, or SCD-2 minted a new
    customer key). We bridge transform-key -> business-key (via the star's own
    dimensions) -> DB-key (via the live dimension tables), so every fact row
    references the real, current dimension row.
    """
    # The DB autoincrements sale_id, so we hand back every fact column except
    # the surrogate; the natural key drives the upsert and keys never collide.
    cols = [c.name for c in wh.fact_sales.columns if c.name != "sale_id"]

    fact = star.fact_sales
    if fact.empty:
        return fact.reindex(columns=cols)

    # transform product_key -> stock_code (from the star we just built)
    prod_bridge = star.dim_product[["product_key", "stock_code"]]
    cust_bridge = star.dim_customer[["customer_key", "customer_id"]]

    # live business-key -> DB surrogate key
    db_prod = pd.read_sql(
        select(wh.dim_product.c.product_key, wh.dim_product.c.stock_code), conn
    ).rename(columns={"product_key": "db_product_key"})
    db_cust = pd.read_sql(
        select(wh.dim_customer.c.customer_key, wh.dim_customer.c.customer_id).where(
            wh.dim_customer.c.is_current == True  # noqa: E712
        ),
        conn,
    ).rename(columns={"customer_key": "db_customer_key"})

    df = (
        fact.merge(prod_bridge, on="product_key", how="left")
        .merge(db_prod, on="stock_code", how="left")
        .merge(cust_bridge, on="customer_key", how="left")
        .merge(db_cust, on="customer_id", how="left")
    )

    # Every fact FK must resolve to a live dimension row. Dimensions are always
    # upserted before this runs, so an unresolved key signals a real bug -- fail
    # loudly here rather than with an opaque pandas NA->int cast error later.
    if df["db_product_key"].isna().any() or df["db_customer_key"].isna().any():
        raise RuntimeError(
            "Fact rows could not be re-keyed to live dimensions "
            "(unresolved product/customer business key); refusing to load "
            "rows that would violate referential integrity."
        )

    df["product_key"] = df["db_product_key"].astype("int64")
    df["customer_key"] = df["db_customer_key"].astype("int64")
    return df[cols]


def _frame_for(star: StarSchema, name: str) -> pd.DataFrame:
    tables = dict(star.tables())
    df = tables[name]
    # Keep only declared columns, in declared order.
    cols = [c.name for c in wh.table_by_name(name).columns]
    present = [c for c in cols if c in df.columns]
    return df[present]


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def load_star_schema(star: StarSchema, config: Config) -> dict[str, int]:
    """Write all warehouse tables to the configured DB using ``load_mode``.

    Returns a mapping of table name -> rows written/affected this run.
    """
    mode = config.load_mode
    if mode not in VALID_LOAD_MODES:
        raise ValueError(
            f"Unknown PIPEFORGE_LOAD_MODE={mode!r}; expected one of {VALID_LOAD_MODES}"
        )

    engine = _make_engine(config)
    try:
        ensure_schema(engine)
        with engine.begin() as conn:
            if mode == "replace":
                return _load_replace(conn, star)
            if mode == "append":
                return _load_append(conn, star)
            return _load_merge(conn, star)
    finally:
        engine.dispose()


def read_table(table: str, config: Config):
    """Convenience reader used by tests and the CLI report."""
    engine = create_engine(config.sqlalchemy_url())
    try:
        return pd.read_sql_table(table, engine)
    finally:
        engine.dispose()
