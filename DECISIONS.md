# Design decisions

Short rationales for the choices that shape pipeforge. These are the questions
a senior reviewer tends to ask; the answers live here so they are discoverable
rather than buried in docstrings.

## Why ELT, not ETL

The raw CSV is loaded *as-is* into a faithful "bronze" DataFrame before any
cleaning. Transformation happens afterwards, in its own stage. This keeps the
source reproducible and auditable: the extract layer coerces types (bad values
become `NaN`/`NaT`) but **never drops a row**. What to reject is decided
explicitly in the transform, and reported by the data-quality layer — not
smuggled away during extraction.

## Why quarantine, not delete

Rows that cannot be cleanly modelled (missing customer, non-positive quantity,
missing price, an unparseable date, or a duplicate that would violate the fact
grain) are moved to a `quarantine` table **with a `quarantine_reason`**, not
silently discarded. Nothing disappears without a trace, and the run can report
exactly how much was rejected and why. Post-load reconciliation then checks
`rows_extracted == fact + quarantine`, so a leak would be caught.

## ERROR vs WARNING severity

The data-quality suite mixes two severities on purpose:

* **ERROR** — structural problems that make the dataset unusable (empty
  dataset, null `invoice_no`/`stock_code`). These *abort* the run when
  `PIPEFORGE_FAIL_ON_CHECK=1`.
* **WARNING** — recoverable dirt the transform can quarantine (a stray negative
  quantity, a missing price, a duplicate line). These are recorded but never
  block, because the pipeline has a defined, non-destructive way to handle them.

This split is what lets the bundled dataset ship with deliberate dirt while the
default run still succeeds and demonstrates the quarantine path.

## Surrogate keys, and the fact grain

Dimensions use integer **surrogate keys** (`product_key`, `customer_key`,
`date_key`) so the fact joins are cheap and stable even if a business key
changes. The fact's **natural key** — the grain — is
`(invoice_no, product_key, date_key)`: one row per invoice line. It is declared
`UNIQUE` at the storage layer, which is what makes the idempotent `merge` load
possible and blocks accidental double-loads.

`date_key` is a meaningful `yyyymmdd` integer (its own natural key), so
`dim_date` needs no separate surrogate.

## Explicit schema as the single source of truth

The load stage does **not** rely on `DataFrame.to_sql` type inference. Every
table is declared once as a typed SQLAlchemy `Table` (real types, primary keys,
foreign keys, `NOT NULL`, indexes) in `pipeforge/schema/warehouse.py`. The
database is created from that metadata, so referential integrity is enforced by
the storage layer for both SQLite and Postgres. The Snowflake DDL generator
derives from the *same* declarations, and a data-contract test asserts the
exported DDL and the live schema agree — so the export stubs can never silently
drift from the real warehouse.

## Load modes: replace / append / merge

Real batch warehouses don't drop and rebuild every night, so `PIPEFORGE_LOAD_MODE`
offers three strategies:

* **replace** — drop + rebuild (deterministic; the original one-shot behaviour).
* **append** — upsert dimensions; insert only fact rows past a high-water-mark
  on `date_key`. Re-running an already-seen date is a no-op.
* **merge** — fully idempotent upsert on natural keys everywhere, plus a Type-2
  slowly-changing dimension on `dim_customer`.

`merge` and `append` re-resolve fact foreign keys against the *live* dimension
keys, so a fact never points at a stale surrogate.

## Why Type-2 SCD on `dim_customer`

Customer attributes (here, `country`) change over time, and a warehouse should
preserve that history rather than overwrite it. When a customer's country
changes between runs, the current row is **closed** (`effective_to` set,
`is_current = false`) and a **new versioned row** is opened with a fresh
surrogate key. Facts always resolve to the *current* version. The first version
opens at an epoch date so a same-day change can open a second version without
colliding on `(customer_id, effective_from)`. `--revision` on the dataset
generator produces a deterministic country change to exercise this.

## Observability: run metadata + reconciliation

Every load writes a `pipeline_runs` row (run id, timestamps, load mode, rows
in/out/quarantined, total revenue, git sha) so the pipeline has a lineage and
data-freshness story, chartable in Grafana and the static explorer. After each
load, reconciliation queries the *actual warehouse* (not the in-memory frames)
to assert: no orphan foreign keys, row-count balance, and revenue reconciliation
to the source. A reconciliation failure fails the run.

## Airflow: file hand-offs, not JSON-in-XCom

The DAG stages data between tasks through a **bronze Parquet file** on a shared
path; only the tiny file path travels via XCom. Pushing a whole DataFrame
through XCom as JSON doesn't scale, re-parses the frame in every task, and
relies on a deprecated pandas path. Every task also gets retries with
exponential backoff and an SLA, and CI parses the DAG so it can't rot.

## Why pandas, not Spark

The dataset is intentionally tiny and the goal is a zero-friction local run, so
the transform is a **pandas** pipeline. The stages are clean and swappable, so a
Spark backend could drop into the transform stage — but requiring a cluster
would defeat the "clone and run in seconds" promise. This is a deliberate scope
choice, stated honestly, not a limitation hidden behind buzzwords.
