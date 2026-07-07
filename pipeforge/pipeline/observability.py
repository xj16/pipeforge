"""Run metadata + post-load reconciliation.

Two things the pipeline persists so it has a lineage/observability story
rather than a point-in-time count:

``pipeline_runs``
    One row per run (run_id, timestamps, load mode, rows in/out/quarantined,
    total revenue, git sha). This gives the HTML explorer and Grafana a run
    history to chart and a data-freshness signal.

Post-load reconciliation
    Assertions that query the *actual warehouse* (not the in-memory frames):

    * no orphan foreign keys in ``fact_sales``;
    * ``rows_extracted == fact rows + quarantine rows`` for a full ``replace``;
    * ``SUM(fact.revenue)`` reconciles to the source revenue.

    These are returned as :class:`~pipeforge.checks.core.CheckResult` objects so
    they render with the same PASS/FAIL badges as the extract-time checks.
"""
from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine  # top-level `sqlalchemy.Engine` is 2.0-only

from ..checks.core import CheckResult, Severity
from ..config import Config
from ..schema import warehouse as wh


def new_run_id() -> str:
    return str(uuid.uuid4())


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


@dataclass
class RunMetadata:
    run_id: str
    started_at: datetime
    load_mode: str
    rows_extracted: int
    rows_loaded: int
    rows_quarantined: int
    total_revenue: float

    def persist(self, config: Config) -> None:
        engine = create_engine(config.sqlalchemy_url())
        try:
            wh.metadata.create_all(engine, tables=[wh.pipeline_runs])
            with engine.begin() as conn:
                conn.execute(
                    wh.pipeline_runs.insert().values(
                        run_id=self.run_id,
                        started_at=self.started_at.isoformat(timespec="seconds"),
                        finished_at=datetime.now(timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                        load_mode=self.load_mode,
                        rows_extracted=self.rows_extracted,
                        rows_loaded=self.rows_loaded,
                        rows_quarantined=self.rows_quarantined,
                        total_revenue=round(self.total_revenue, 2),
                        git_sha=_git_sha(),
                    )
                )
        finally:
            engine.dispose()


def _reconcile_result(name: str, passed: bool, observed, threshold, detail: str) -> CheckResult:
    return CheckResult(
        name=name,
        passed=passed,
        severity=Severity.ERROR,
        observed=observed,
        threshold=threshold,
        detail=detail,
    )


def reconcile(
    config: Config,
    *,
    rows_extracted: int,
    rows_quarantined: int,
    source_revenue: float,
) -> list[CheckResult]:
    """Run post-load assertions against the live warehouse.

    Returns a list of :class:`CheckResult`. ``ERROR``-severity failures here
    mean the load is inconsistent with the source and should be treated as a
    hard failure by the caller.
    """
    engine: Engine = create_engine(config.sqlalchemy_url())
    results: list[CheckResult] = []
    try:
        with engine.connect() as conn:
            fact = wh.fact_sales
            n_fact = conn.execute(select(func.count()).select_from(fact)).scalar() or 0

            # 1. No orphan foreign keys: every fact FK resolves to a dimension.
            orphan_products = conn.execute(
                select(func.count()).select_from(fact).where(
                    ~fact.c.product_key.in_(select(wh.dim_product.c.product_key))
                )
            ).scalar() or 0
            orphan_customers = conn.execute(
                select(func.count()).select_from(fact).where(
                    ~fact.c.customer_key.in_(select(wh.dim_customer.c.customer_key))
                )
            ).scalar() or 0
            orphan_dates = conn.execute(
                select(func.count()).select_from(fact).where(
                    ~fact.c.date_key.in_(select(wh.dim_date.c.date_key))
                )
            ).scalar() or 0
            orphans = int(orphan_products) + int(orphan_customers) + int(orphan_dates)
            results.append(
                _reconcile_result(
                    "recon_no_orphan_fks",
                    passed=orphans == 0,
                    observed=orphans,
                    threshold=0,
                    detail=(
                        f"{orphan_products} product / {orphan_customers} customer / "
                        f"{orphan_dates} date orphan FK(s)"
                    ),
                )
            )

            # 2. Row-count reconciliation: extract == fact + quarantine.
            #    Only exact for a full replace; for incremental modes we assert
            #    the fact never exceeds what was extracted this run.
            expected = rows_extracted - rows_quarantined
            if config.load_mode == "replace":
                passed = int(n_fact) == expected
                detail = f"fact={n_fact}, expected extract-quarantine={expected}"
            else:
                passed = int(n_fact) >= expected
                detail = (
                    f"fact={n_fact} >= this-run valid={expected} "
                    f"(incremental: fact may hold prior runs)"
                )
            results.append(
                _reconcile_result(
                    "recon_row_counts", passed, int(n_fact), expected, detail
                )
            )

            # 3. Revenue reconciliation: SUM(fact.revenue) matches source.
            db_revenue = conn.execute(select(func.sum(fact.c.revenue))).scalar() or 0
            db_revenue = round(float(db_revenue), 2)
            if config.load_mode == "replace":
                passed = abs(db_revenue - round(source_revenue, 2)) < 0.01
                detail = f"db={db_revenue} vs source={round(source_revenue, 2)}"
            else:
                passed = db_revenue >= round(source_revenue, 2) - 0.01
                detail = f"db={db_revenue} >= this-run source={round(source_revenue, 2)}"
            results.append(
                _reconcile_result(
                    "recon_revenue",
                    passed,
                    db_revenue,
                    round(source_revenue, 2),
                    detail,
                )
            )
    finally:
        engine.dispose()
    return results


def read_run_history(config: Config) -> pd.DataFrame:
    """Return the ``pipeline_runs`` table (empty frame if it does not exist)."""
    engine = create_engine(config.sqlalchemy_url())
    try:
        wh.metadata.create_all(engine, tables=[wh.pipeline_runs])
        return pd.read_sql_table("pipeline_runs", engine)
    finally:
        engine.dispose()
