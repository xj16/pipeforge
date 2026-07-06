"""Airflow DAG for the pipeforge ELT pipeline.

Each pipeline stage becomes an Airflow task so you get retries, scheduling
and the graph view "for free". The DAG imports the same pipeforge functions
the CLI uses -- there is no logic duplicated here.

This file is only parsed by Airflow inside the docker-compose stack; it is
never imported by the core package or the tests, so pipeforge has no runtime
dependency on Airflow.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from pipeforge.checks.core import CheckSuite
from pipeforge.config import default_config
from pipeforge.pipeline.extract import extract_orders
from pipeforge.pipeline.load import load_star_schema
from pipeforge.pipeline.run import PipelineError, run_quality
from pipeforge.schema.star import build_star_schema

DEFAULT_ARGS = {
    "owner": "pipeforge",
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}


def _extract(**context):
    config = default_config()
    df = extract_orders(config.raw_dir)
    # Push through XCom as JSON so downstream tasks can rebuild it.
    context["ti"].xcom_push(key="raw", value=df.to_json(orient="split", date_format="iso"))


def _quality(**context):
    import pandas as pd

    raw_json = context["ti"].xcom_pull(key="raw", task_ids="extract")
    df = pd.read_json(raw_json, orient="split")
    results = run_quality(df)
    print(CheckSuite.summarize(results))
    if default_config().fail_on_check_error and CheckSuite.has_blocking_failure(results):
        raise PipelineError("Blocking data-quality check failed")


def _transform_load(**context):
    import pandas as pd

    raw_json = context["ti"].xcom_pull(key="raw", task_ids="extract")
    df = pd.read_json(raw_json, orient="split")
    star = build_star_schema(df)
    written = load_star_schema(star, default_config())
    print("Loaded:", written)


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

    extract >> quality >> transform_load
