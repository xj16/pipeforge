"""The ELT orchestrator: extract -> quality -> transform -> load.

This is the single entry point the CLI and the Airflow DAG both call.
Each stage is also individually importable so Airflow can run them as
separate tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..checks import build_default_suite
from ..checks.core import CheckResult, CheckSuite
from ..config import Config, default_config
from ..schema.star import StarSchema, build_star_schema
from .extract import extract_orders
from .load import load_star_schema


class PipelineError(RuntimeError):
    """Raised when a blocking data-quality check fails."""


@dataclass
class PipelineResult:
    """Everything a run produced -- useful for tests and reporting."""

    check_results: list[CheckResult]
    star: StarSchema
    rows_written: dict[str, int] = field(default_factory=dict)

    @property
    def total_revenue(self) -> float:
        fact = self.star.fact_sales
        return round(float(fact["revenue"].sum()), 2) if len(fact) else 0.0


def run_quality(raw: pd.DataFrame) -> list[CheckResult]:
    suite = build_default_suite()
    return suite.run(raw)


def run_pipeline(config: Config | None = None, *, load: bool = True) -> PipelineResult:
    """Run the full ELT pipeline.

    Parameters
    ----------
    config:
        Runtime config. Defaults to :func:`default_config`.
    load:
        When False, skip the database write (used by tests that only care
        about the transform output). Extract, checks and transform always run.
    """
    config = config or default_config()

    # 1. Extract
    raw = extract_orders(config.raw_dir)

    # 2. Data-quality checks
    results = run_quality(raw)
    if config.fail_on_check_error and CheckSuite.has_blocking_failure(results):
        summary = CheckSuite.summarize(results)
        raise PipelineError(
            "Blocking data-quality check(s) failed:\n" + summary
        )

    # 3. Transform into star schema (quarantines dirty rows)
    star = build_star_schema(raw)

    # 4. Load
    rows_written: dict[str, int] = {}
    if load:
        rows_written = load_star_schema(star, config)

    return PipelineResult(check_results=results, star=star, rows_written=rows_written)
