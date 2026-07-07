<div align="center">

# pipeforge

**A runnable batch ELT pipeline you can clone and run in seconds — extract,
validate, model into a Kimball star schema, and load, with incremental &
idempotent loads, Type-2 dimension history, and a one-click static dashboard.**

[![CI](https://github.com/xj16/pipeforge/actions/workflows/ci.yml/badge.svg)](https://github.com/xj16/pipeforge/actions/workflows/ci.yml)
[![coverage](https://img.shields.io/badge/coverage-~94%25-2ea043)](https://github.com/xj16/pipeforge/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)](https://www.python.org/)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![live demo](https://img.shields.io/badge/live_demo-static_explorer-f0883e)](docs/index.html)

</div>

pipeforge is a realistic-but-tiny reference for how a batch ELT job actually
fits together: **extract → validate → model → load → serve**, with tests around
every stage. No cloud account, no paid API, and no Docker required for the core.
It takes a bundled retail dataset, runs **data-quality checks**, transforms it
into a proper **star schema**, and loads it into **SQLite** (default) or
**Postgres** — then can emit a **self-contained HTML dashboard** or drive a full
**Airflow + Grafana** stack.

![architecture](docs/architecture.svg)

---

## Quick start (no Docker, ~30 seconds)

```bash
pip install -r requirements.txt      # two core deps: pandas + SQLAlchemy
python -m pipeforge run              # full ELT into a local SQLite warehouse
python -m pipeforge report           # inspect the star schema + revenue by category
python -m pipeforge export --html    # build the static dashboard -> docs/index.html
```

`run` generates the bundled dataset if missing, extracts it, runs the
data-quality suite, builds the star schema, quarantines dirty rows, loads every
table, then **reconciles the load against the source** and records run metadata.

```
Data-quality checks:
  [PASS] row_count_at_least (observed=601, threshold=100, error)
  [FAIL] non_negative[quantity] (observed=1, ... warning) -- 1 negative value(s)
  [FAIL] unique[invoice_no+stock_code+invoice_date] (... warning) -- 1 duplicate row(s)

Post-load reconciliation:
  [PASS] recon_no_orphan_fks (observed=0, threshold=0, error)
  [PASS] recon_row_counts (observed=597, threshold=597, error)
  [PASS] recon_revenue (observed=59289.12, threshold=59289.12, error)

Warehouse tables written:
  dim_product      10 rows
  dim_customer     10 rows
  dim_date        175 rows
  fact_sales      597 rows
  quarantine        4 rows

Total revenue (fact_sales): 59,289.12
```

---

## Live demo (zero dependencies)

The single biggest thing a reviewer wants is to *see the output* without booting
infrastructure. `python -m pipeforge export --html` runs the pipeline against
the bundled data and writes one self-contained **`docs/index.html`** — the six
Grafana panels rendered as hand-rolled inline SVG (no JS libraries, no CDN, no
network): revenue-by-category donut, revenue-by-country bars, a daily-revenue
line, a quarantine-reason breakdown, and the DQ + reconciliation table with
PASS/FAIL badges. Open it straight from the repo.

---

## Features

- **Real pandas ELT pipeline** — `extract → quality → transform → load →
  reconcile`, each stage independently importable and unit-tested.
- **Incremental & idempotent loads** — `PIPEFORGE_LOAD_MODE=replace|append|merge`.
  `append` uses a high-water-mark on `date_key`; `merge` is a dialect-aware
  `INSERT … ON CONFLICT` upsert on the fact's natural key. Re-running is safe.
- **Type-2 slowly-changing dimension** on `dim_customer` — country changes close
  the old version and open a new one; facts track the current version.
- **Explicit typed warehouse schema** — declared SQLAlchemy tables with PKs,
  fact→dim FKs, `NOT NULL`, a unique fact grain, and indexes. Integrity is
  enforced at the storage layer, and the Snowflake DDL derives from the *same*
  source of truth (a test asserts they never drift).
- **Observability** — a `pipeline_runs` table (run id, timestamps, row counts,
  revenue, git sha) plus post-load reconciliation that queries the real DB for
  orphan FKs, row-count balance, and revenue reconciliation.
- **Home-grown data-quality checks** — `not_null`, `non_negative`, `unique`,
  `in_set`, `row_count_at_least` with `ERROR`/`WARNING` severities. No heavy
  dependency; `ERROR` aborts, `WARNING` is recorded and quarantined downstream.
- **Static HTML dashboard** — dependency-free inline-SVG charts, one command.
- **Airflow DAG** that reuses the exact pipeline functions and hands off a bronze
  Parquet file between tasks (retries, backoff, SLAs) — not JSON-in-XCom.
- **docker-compose stack**: Postgres + Airflow + Grafana with a pre-provisioned
  dashboard, plus a lightweight `demo` profile for the static explorer.
- **Offline export stubs** for Snowflake (typed DDL) and Databricks (Parquet/CSV
  + load SQL) — never need a paid account.
- **CI**: tests on Python 3.11/3.12 with coverage gating, a full ELT against a
  real Postgres service, an Airflow DAG-parse smoke test, and a static-demo build.

---

## Commands

```bash
python -m pipeforge run              # full ELT into the warehouse (+ reconcile)
python -m pipeforge check            # data-quality checks only (no DB write)
python -m pipeforge report           # print warehouse tables + revenue by category
python -m pipeforge export           # write Snowflake/Databricks export stubs
python -m pipeforge export --html    # build the static warehouse explorer
python -m pipeforge generate-data    # (re)generate the bundled dataset
```

Installed as a console script too (`pip install -e .` → `pipeforge run`).

### Dataset generator options

```bash
python -m pipeforge.generate_dataset --rows 10000        # scale up
python -m pipeforge.generate_dataset --revision 1        # move a customer's country (SCD-2)
python -m pipeforge.generate_dataset --profile           # per-column null/min/max/distinct
```

---

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PIPEFORGE_WAREHOUSE` | `sqlite` | `sqlite` or `postgres` |
| `PIPEFORGE_LOAD_MODE` | `replace` | `replace`, `append`, or `merge` |
| `PIPEFORGE_SQLITE_PATH` | `data/warehouse/pipeforge.db` | SQLite file path |
| `PIPEFORGE_POSTGRES_URL` | `postgresql+psycopg2://pipeforge:pipeforge@localhost:5432/pipeforge` | SQLAlchemy URL |
| `PIPEFORGE_FAIL_ON_CHECK` | `1` | `1` = abort on `ERROR`-severity check; `0` = continue |

### Targeting Postgres

```bash
export PIPEFORGE_WAREHOUSE=postgres
export PIPEFORGE_POSTGRES_URL="postgresql+psycopg2://pipeforge:pipeforge@localhost:5432/pipeforge"
pip install psycopg2-binary
python -m pipeforge run
```

### Demonstrating incremental loads & SCD-2

```bash
PIPEFORGE_LOAD_MODE=merge python -m pipeforge run          # idempotent: re-run is a no-op
python -m pipeforge.generate_dataset --revision 1          # one customer moves country
PIPEFORGE_LOAD_MODE=merge python -m pipeforge run          # dim_customer gains a 2nd version
```

---

## Architecture

- **ELT, not ETL** — the raw CSV is loaded as a faithful "bronze" copy; cleaning
  and modelling happen afterwards, and no row is ever silently dropped.
- **Star schema** — three conformed dimensions (`dim_product`, `dim_customer`,
  `dim_date`) around one `fact_sales` grain (one row per invoice line), joined by
  integer surrogate keys.
- **Quarantine, not delete** — rows that can't be cleanly modelled go to a
  `quarantine` table *with a reason*.
- **One orchestrator, three drivers** — the CLI, the Airflow DAG, and CI all call
  the same stage functions; no duplicated logic.

The full rationale (why ELT, the ERROR/WARNING split, surrogate-key strategy,
SCD-2, load modes) lives in **[DECISIONS.md](DECISIONS.md)**.

### Data model

```
dim_product(product_key PK, stock_code, description, category, unit_price)
dim_customer(customer_key PK, customer_id, country,
             effective_from, effective_to, is_current)     -- Type-2 SCD
dim_date(date_key PK, date, year, quarter, month, day, weekday, is_weekend)

fact_sales(sale_id PK,
           product_key  FK -> dim_product,
           customer_key FK -> dim_customer,
           date_key     FK -> dim_date,
           invoice_no, quantity, unit_price, revenue,
           UNIQUE(invoice_no, product_key, date_key))       -- the grain

quarantine(... raw columns ..., quarantine_reason)
pipeline_runs(run_id PK, started_at, finished_at, load_mode,
              rows_extracted, rows_loaded, rows_quarantined, total_revenue, git_sha)
```

Runnable examples live in [`sql/example_queries.sql`](sql/example_queries.sql).

---

## The full experience with Docker (Airflow + Postgres + Grafana)

```bash
docker compose up -d
```

- **Airflow** → http://localhost:8080 (`airflow`/`airflow`). The `pipeforge_elt`
  DAG is unpaused; trigger it to populate the Postgres warehouse.
- **Grafana** → http://localhost:3000 (`admin`/`admin`). The auto-provisioned
  dashboard charts total revenue, orders, quarantined rows, revenue by
  category/country, daily revenue, quarantine reasons, and **pipeline run history**.

Or just the infra-free static demo:

```bash
docker compose --profile demo up demo    # -> http://localhost:8000
```

The core pandas pipeline needs none of this — Docker is only for the
orchestrated + dashboarded experience.

---

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest -q                                        # 62 tests
pytest --cov=pipeforge --cov-report=term-missing # with coverage (~94%)
```

The suite covers extraction/typing, every data-quality check, star-schema
integrity, the three load modes + watermark, SCD-2 versioning, post-load
reconciliation, the schema/DDL data contract, the static HTML explorer, the CLI,
and the parametrized dataset generator.

---

## Project layout

```
pipeforge/
  config.py              # env-driven runtime config (warehouse + load mode)
  generate_dataset.py    # deterministic dataset generator (--rows/--revision/--profile)
  cli.py                 # `python -m pipeforge ...` entry point
  pipeline/
    extract.py           # CSV -> typed DataFrame (bronze)
    run.py               # the ELT orchestrator (+ reconcile + run metadata)
    load.py              # replace/append/merge loads, SCD-2, dialect-aware upsert
    observability.py     # pipeline_runs + post-load reconciliation
  checks/                # home-grown data-quality framework + default suite
  schema/
    star.py              # star-schema transform + quarantine logic
    warehouse.py         # typed SQLAlchemy schema: the single source of truth
  export/                # Snowflake DDL, Databricks Parquet, static HTML explorer
dags/                    # Airflow DAG (bronze Parquet hand-off, retries, SLAs)
docker/                  # Airflow image, Postgres init, Grafana provisioning
docs/                    # architecture.svg + generated index.html (static demo)
sql/                     # example analytical queries
tests/                   # pytest suite (62 tests)
.github/workflows/ci.yml # CI: tests+coverage, Postgres ELT, DAG parse, static demo
```

---

## Tech stack

**Python** (3.10+) · **pandas** (transform) · **SQLAlchemy Core** (typed schema
& warehouse I/O) · **SQLite** / **Postgres** (targets) · **Apache Airflow**
(orchestration) · **Docker Compose** (Airflow + Postgres + Grafana) · **Grafana**
(dashboards) · **GitHub Actions** (CI). Offline **Snowflake** / **Databricks**
export stubs. The static dashboard is hand-rolled inline SVG — zero dependencies.

> Why pandas, not Spark: the dataset is intentionally small and the goal is a
> zero-friction local run. The stages are swappable, so a Spark backend could
> drop into the transform — but a cluster is deliberately not required. See
> [DECISIONS.md](DECISIONS.md).

## License

MIT © 2026 xj16 — see [LICENSE](LICENSE).
