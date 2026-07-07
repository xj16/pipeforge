# Changelog

All notable changes to pipeforge are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-07

The "real batch warehouse" pass: pipeforge stops being a one-shot rebuild and
gains incremental loading, dimensional history, storage-level integrity, an
observability story, and a zero-dependency live demo.

### Added

- **Incremental / idempotent load modes** (`PIPEFORGE_LOAD_MODE`):
  - `replace` (default) — drop + rebuild, as before.
  - `append` — high-water-mark on `date_key`; only new-date fact rows are
    inserted, dimensions upserted. Re-running a seen date is a no-op.
  - `merge` — fully idempotent upsert on natural keys via dialect-aware
    `INSERT … ON CONFLICT` (SQLite and Postgres).
- **Type-2 slowly-changing dimension on `dim_customer`** — a country change
  closes the old version (`effective_to`, `is_current=false`) and opens a new
  versioned row; facts resolve to the current version.
- **Explicit, typed warehouse schema** (`pipeforge/schema/warehouse.py`) —
  SQLAlchemy `Table` definitions with primary keys, fact→dim foreign keys,
  `NOT NULL` on keys, a unique fact grain, and indexes. Referential integrity
  is now enforced at the storage layer (FK pragma enabled on SQLite).
- **Run metadata + post-load reconciliation** — every run writes a
  `pipeline_runs` row (run id, timestamps, load mode, rows in/out/quarantined,
  total revenue, git sha) and runs assertions against the live DB: no orphan
  FKs, row-count balance, and revenue reconciliation to source. A failure fails
  the run.
- **Static in-browser warehouse explorer** — `pipeforge export --html` emits a
  single self-contained `docs/index.html` with dependency-free inline-SVG
  charts (revenue by category/country, daily-revenue line, quarantine reasons)
  and the DQ + reconciliation table. Mirrors the Grafana panels with no Docker.
- **Dataset generator flags** — `--rows`, `--seed`, `--revision` (deterministic
  customer country change to exercise SCD-2 / merge), and a `--profile` summary.
- **Docker**: a minimal core `Dockerfile` and a `demo` compose profile
  (`docker compose --profile demo up demo`) that builds and serves the static
  explorer at `http://localhost:8000`.
- **Docs**: `DECISIONS.md` (design rationale), a rendered `docs/architecture.svg`
  diagram, and expanded example queries (SCD-2 history, run lineage).
- **CI**: coverage gating (`--cov-fail-under=85`), a coverage artifact, an
  Airflow **DAG-parse** job, a **static-demo** build+artifact job, and merge-mode
  re-runs on both SQLite and Postgres.

### Changed

- **Load stage** rewritten to create tables from the declared schema and bulk
  insert through SQLAlchemy Core instead of `DataFrame.to_sql` type inference.
- **Snowflake DDL export** now derives from the declared schema (real types,
  PKs, FKs) — one source of truth — instead of pandas dtypes.
- **Airflow DAG** hands off a bronze **Parquet file** on a shared path (only the
  path via XCom) instead of pushing the whole DataFrame as JSON; adds per-task
  retries with backoff, SLAs, and a cleanup task. Removes the deprecated
  `pandas.read_json(str)` path.
- **Transform** quarantines duplicate invoice lines (`duplicate_invoice_line`)
  so the fact grain is genuinely unique; `dim_customer` carries SCD-2 columns.
- **Grafana dashboard** adds *Quarantine reasons* and *Pipeline run history*
  panels; revenue-by-country filters to the current customer version.

### Tests

- Grew from 28 to 62 tests. New flagship suites over the hardest subsystems:
  load modes + watermark, SCD-2 versioning, post-load reconciliation, the
  schema/DDL data contract, the HTML explorer (including XSS-escaping), the CLI,
  and the parametrized generator. Coverage ≈ 94%.

## [0.1.0] - 2026-07-07

Initial release: a runnable batch ELT pipeline over a bundled retail dataset —
extract → data-quality checks → Kimball star schema → SQLite/Postgres load, with
an Airflow DAG, a docker-compose (Airflow + Postgres + Grafana) stack, offline
Snowflake/Databricks export stubs, and a 28-test suite.

[0.2.0]: https://github.com/xj16/pipeforge/releases/tag/v0.2.0
[0.1.0]: https://github.com/xj16/pipeforge/releases/tag/v0.1.0
