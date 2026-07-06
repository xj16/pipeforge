# pipeforge

**One-command local data-engineering playground.**

pipeforge is a runnable, tested **batch ELT pipeline** you can clone and run in
seconds — no cloud account, no paid API, no Docker required for the core. It
takes a bundled retail dataset, runs **data-quality checks**, transforms it into
a proper **Kimball star schema**, and loads it into **SQLite** (default) or
**Postgres**. On top of that it ships **Airflow DAGs** and a **docker-compose**
stack (Airflow + Postgres + **Grafana**) for the full, orchestrated experience.

It exists to be a realistic-but-tiny reference for how a batch ELT job actually
fits together: extract → validate → model → load → visualise, with tests around
every stage.

```
 raw CSV ──► extract ──► data-quality checks ──► star-schema transform ──► load ──► warehouse
 (bronze)   (pandas)     (nulls, negatives,       (dim_product/customer/     (SQLite    │
                          duplicates, ranges)       date + fact_sales,         or PG)    ▼
                                                    dirty rows quarantined)          Grafana
```

---

## Quick start (no Docker, ~30 seconds)

```bash
# 1. install the two core deps
pip install -r requirements.txt

# 2. run the full ELT into a local SQLite warehouse
python -m pipeforge run

# 3. inspect the resulting star schema
python -m pipeforge report
```

That's it. `python -m pipeforge run` generates the bundled dataset if missing,
extracts it, runs the data-quality suite, builds the star schema, quarantines
the dirty rows, and writes every table to `data/warehouse/pipeforge.db`.

Example output:

```
Data-quality checks:
  [PASS] row_count_at_least (observed=601, threshold=100, error)
  [PASS] not_null[invoice_no] ...
  [FAIL] non_negative[quantity] (observed=1, ... warning) -- 1 negative value(s)
  [FAIL] unique[invoice_no+stock_code+invoice_date] (... warning) -- 1 duplicate row(s)

Warehouse tables written:
  dim_product      10 rows
  dim_customer     10 rows
  dim_date        175 rows
  fact_sales      598 rows
  quarantine        3 rows

Total revenue (fact_sales): 59,297.62
```

---

## Why ELT, and why a star schema?

- **ELT, not ETL:** the raw CSV is loaded *as-is* (the "bronze" layer stays a
  faithful copy of the source), and transformation happens afterwards. The
  extract stage never silently drops rows — that decision is made explicitly and
  reported.
- **Star schema:** the analytical model is three conformed dimensions
  (`dim_product`, `dim_customer`, `dim_date`) around one `fact_sales` grain
  (one row per invoice line). Surrogate integer keys join fact → dimensions, so
  Grafana / BI queries are simple `JOIN`s.
- **Quarantine, not delete:** rows that can't be cleanly modelled (missing
  customer, non-positive quantity, missing price) are moved to a `quarantine`
  table *with a reason*, so nothing disappears without a trace.

---

## Features

- **Real pandas ELT pipeline** — `extract → quality → transform → load`, each
  stage independently importable and unit-tested.
- **Bundled, reproducible dataset** — a small "Online Retail"-style CSV shipped
  in the repo and regenerable deterministically
  (`python -m pipeforge.generate-data`), seeded with deliberate dirty rows.
- **Home-grown data-quality checks** — a miniature validation layer
  (`not_null`, `non_negative`, `unique`, `in_set`, `row_count_at_least`) with
  `ERROR`/`WARNING` severities. `ERROR`-level failures abort the run;
  `WARNING`s are recorded. No heavy dependency required.
- **Kimball star schema** with surrogate keys, a generated date dimension, and a
  quarantine table for rejected rows.
- **SQLite or Postgres** target, switched entirely by environment variable
  (`PIPEFORGE_WAREHOUSE`).
- **Airflow DAG** (`dags/pipeforge_elt_dag.py`) that reuses the exact same
  pipeline functions — no duplicated logic.
- **docker-compose stack**: Postgres + Airflow (webserver & scheduler) +
  Grafana, with a **pre-provisioned Grafana dashboard** that charts the star
  schema live.
- **Optional export stubs** for **Snowflake** (DDL generator) and **Databricks**
  (Parquet/CSV + load SQL) — fully offline, never required, never need a paid
  account.
- **CI** (GitHub Actions) that runs the tests on Python 3.11/3.12 and also
  executes the full ELT against a real Postgres service.

---

## Commands

```bash
python -m pipeforge run            # full ELT into the warehouse
python -m pipeforge check          # data-quality checks only (no DB write)
python -m pipeforge report         # print warehouse tables + revenue by category
python -m pipeforge export         # write Snowflake/Databricks export stubs
python -m pipeforge generate-data  # (re)generate the bundled dataset
```

If you `pip install -e .`, the same commands are available as the `pipeforge`
console script (e.g. `pipeforge run`).

---

## Targeting Postgres

```bash
export PIPEFORGE_WAREHOUSE=postgres
export PIPEFORGE_POSTGRES_URL="postgresql+psycopg2://pipeforge:pipeforge@localhost:5432/pipeforge"
pip install psycopg2-binary        # only needed for Postgres
python -m pipeforge run
```

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PIPEFORGE_WAREHOUSE` | `sqlite` | `sqlite` or `postgres` |
| `PIPEFORGE_SQLITE_PATH` | `data/warehouse/pipeforge.db` | SQLite file path |
| `PIPEFORGE_POSTGRES_URL` | `postgresql+psycopg2://pipeforge:pipeforge@localhost:5432/pipeforge` | SQLAlchemy URL |
| `PIPEFORGE_FAIL_ON_CHECK` | `1` | `1` = abort on `ERROR`-severity check; `0` = continue |

---

## The full experience with Docker (Airflow + Postgres + Grafana)

```bash
docker compose up -d
```

- **Airflow** → http://localhost:8080 (user `airflow` / pass `airflow`). The
  `pipeforge_elt` DAG is unpaused; trigger it (or wait for `@daily`) to populate
  the Postgres warehouse.
- **Grafana** → http://localhost:3000 (user `admin` / pass `admin`). The
  **"pipeforge – Retail Sales Star Schema"** dashboard is auto-provisioned and
  reads straight from the warehouse: total revenue, orders, quarantined rows,
  revenue by category / country, and a daily-revenue time series.

The core pandas pipeline does **not** need any of this — Docker is purely for the
orchestrated + dashboarded experience.

---

## Data model

```
dim_product(product_key PK, stock_code, description, category, unit_price)
dim_customer(customer_key PK, customer_id, country)
dim_date(date_key PK, date, year, quarter, month, day, weekday, is_weekend)

fact_sales(sale_id PK,
           product_key  FK -> dim_product,
           customer_key FK -> dim_customer,
           date_key     FK -> dim_date,
           invoice_no, quantity, unit_price, revenue)

quarantine(... raw columns ..., quarantine_reason)
```

Example analytical query (works on SQLite or Postgres):

```sql
SELECT p.category, ROUND(SUM(f.revenue), 2) AS revenue
FROM fact_sales f
JOIN dim_product p ON f.product_key = p.product_key
GROUP BY p.category
ORDER BY revenue DESC;
```

More runnable examples live in [`sql/example_queries.sql`](sql/example_queries.sql).

---

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite (28 tests) covers extraction/typing, every data-quality check,
star-schema integrity (unique surrogate keys, resolvable foreign keys, no dirty
rows leaking into the fact, revenue arithmetic), an end-to-end run that loads
and re-reads a temp SQLite DB, blocking-failure handling, and the export stubs.

---

## Project layout

```
pipeforge/
  config.py              # env-driven runtime config (SQLite/Postgres)
  generate_dataset.py    # deterministic bundled-dataset generator
  cli.py                 # `python -m pipeforge ...` entry point
  pipeline/
    extract.py           # CSV -> typed DataFrame (bronze)
    run.py               # the ELT orchestrator
    load.py              # write star schema to the warehouse
  checks/                # home-grown data-quality framework + default suite
  schema/star.py         # star-schema transform + quarantine logic
  export/                # offline Snowflake / Databricks export stubs
dags/                    # Airflow DAG reusing the pipeline functions
docker/                  # Airflow image, Postgres init, Grafana provisioning
data/raw/                # bundled dataset (committed)
sql/                     # example analytical queries
tests/                   # pytest suite
.github/workflows/ci.yml # CI: tests on 3.11/3.12 + ELT against Postgres
```

---

## Tech stack

**Python** (3.10+) · **pandas** (transform) · **SQLAlchemy** (warehouse I/O) ·
**SQLite** / **Postgres** (targets) · **Apache Airflow** (orchestration DAG) ·
**Docker Compose** (Airflow + Postgres + Grafana stack) · **Grafana**
(dashboards) · **GitHub Actions** (CI). Optional offline **Snowflake** /
**Databricks** export stubs.

> Note on "Apache Spark": pipeforge's transform is deliberately a **pandas**
> pipeline because the dataset is small and the goal is a zero-friction local
> run. The pipeline is structured in clean, swappable stages so a Spark backend
> could be dropped into the transform stage — see the `schema/` module — but a
> Spark cluster is intentionally *not* required to run or test anything here.

## License

MIT © 2026 xj16 — see [LICENSE](LICENSE).
