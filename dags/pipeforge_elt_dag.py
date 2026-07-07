"""Airflow DAG for the pipeforge ELT pipeline.

Each pipeline stage becomes an Airflow task so you get retries, scheduling
and the graph view "for free". The DAG imports the same pipeforge functions
the CLI uses -- there is no business logic duplicated here.

Task hand-off strategy
----------------------
Tasks hand off through a **bronze Parquet file on a shared path**, not by
pushing the whole DataFrame through XCom as JSON. Only the tiny file *path*
travels via XCom. This is how a real batch pipeline stages data between
operators: it scales past XCom's size limits, avoids re-serialising the frame
in every task, and gives you an inspectable artifact per run. (CSV is used as
an automatic fallback if pyarrow is unavailable.)

This file is only parsed by Airflow inside the docker-compose stack; it is
never imported by the core package or the tests, so pipeforge has no runtime
dependency on Airflow.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

from pipeforge.checks.core import CheckSuite
from pipeforge.config import default_config
from pipeforge.pipeline.extract import extract_orders
from pipeforge.pipeline.load import load_star_schema
from pipeforge.pipeline.observability import reconcile
from pipeforge.pipeline.run import PipelineError, run_quality
from pipeforge.schema.star import build_star_schema

DEFAULT_ARGS = {
    "owner": "pipeforge",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(minutes=10),
    "sla": timedelta(minutes=30),
}

# Shared staging area for the bronze hand-off. Lives under the mounted data
# volume so every task (and the host) can read the same file and inspect it.
STAGING_DIR = Path("/opt/airflow/data/staging")


def _read_bronze(path: str):
    """Read the staged bronze frame back (Parquet, else CSV)."""
    import pandas as pd

    p = Path(path)
    if p.suffix == ".parquet":
        return pd.read_parquet(p)
    # CSV fallback: re-parse date column that CSV can't round-trip typed.
    df = pd.read_csv(p)
    if "invoice_date" in df.columns:
        df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")
    return df


def _extract(**context):
    config = default_config()
    df = extract_orders(config.raw_dir)

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    run_id = context["run_id"]
    try:
        target = STAGING_DIR / f"bronze_{run_id}.parquet"
        df.to_parquet(target, index=False)
    except Exception:  # pyarrow missing -> CSV fallback
        target = STAGING_DIR / f"bronze_{run_id}.csv"
        df.to_csv(target, index=False)

    # Only the small path travels through XCom, never the whole frame.
    context["ti"].xcom_push(key="bronze_path", value=str(target))


def _quality(**context):
    path = context["ti"].xcom_pull(key="bronze_path", task_ids="extract")
    df = _read_bronze(path)
    results = run_quality(df)
    print(CheckSuite.summarize(results))
    if default_config().fail_on_check_error and CheckSuite.has_blocking_failure(results):
        raise PipelineError("Blocking data-quality check failed")


def _transform_load(**context):
    config = default_config()
    path = context["ti"].xcom_pull(key="bronze_path", task_ids="extract")
    df = _read_bronze(path)

    star = build_star_schema(df)
    written = load_star_schema(star, config)
    print("Loaded:", written)

    # Post-load reconciliation against the live warehouse.
    recon = reconcile(
        config,
        rows_extracted=len(df),
        rows_quarantined=len(star.quarantine),
        source_revenue=round(float(star.fact_sales["revenue"].sum()), 2),
    )
    print(CheckSuite.summarize(recon))
    if any(not r.passed for r in recon):
        raise PipelineError("Post-load reconciliation failed")


def _cleanup(**context):
    """Remove this run's bronze staging file."""
    path = context["ti"].xcom_pull(key="bronze_path", task_ids="extract")
    if path:
        Path(path).unlink(missing_ok=True)


with DAG(
    dag_id="pipeforge_elt",
    description="Batch ELT: extract -> quality -> transform -> load (star schema)",
    default_args=DEFAULT_ARGS,
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["pipeforge", "elt", "star-schema"],
) as dag:
    extract = PythonOperator(task_id="extract", python_callable=_extract)
    quality = PythonOperator(task_id="quality_checks", python_callable=_quality)
    transform_load = PythonOperator(
        task_id="transform_load", python_callable=_transform_load
    )
    cleanup = PythonOperator(
        task_id="cleanup", python_callable=_cleanup, trigger_rule="all_done"
    )

    extract >> quality >> transform_load >> cleanup
