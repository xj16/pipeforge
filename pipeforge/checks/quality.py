"""Concrete, reusable data-quality checks and the default suite."""
from __future__ import annotations

import pandas as pd

from .core import CheckResult, CheckSuite, Severity


def not_null(column: str, max_null_fraction: float = 0.0,
             severity: Severity = Severity.ERROR):
    """Fail if the null fraction of ``column`` exceeds ``max_null_fraction``."""

    def _check(df: pd.DataFrame) -> CheckResult:
        total = len(df)
        null_count = int(df[column].isna().sum()) if total else 0
        fraction = (null_count / total) if total else 0.0
        return CheckResult(
            name=f"not_null[{column}]",
            passed=fraction <= max_null_fraction,
            severity=severity,
            observed=round(fraction, 4),
            threshold=max_null_fraction,
            detail=f"{null_count}/{total} rows null in '{column}'",
        )

    return _check


def non_negative(column: str, severity: Severity = Severity.ERROR):
    """Fail if any value in ``column`` is negative."""

    def _check(df: pd.DataFrame) -> CheckResult:
        series = pd.to_numeric(df[column], errors="coerce")
        negatives = int((series < 0).sum())
        return CheckResult(
            name=f"non_negative[{column}]",
            passed=negatives == 0,
            severity=severity,
            observed=negatives,
            threshold=0,
            detail=f"{negatives} negative value(s) in '{column}'",
        )

    return _check


def unique(columns: list[str], severity: Severity = Severity.WARNING):
    """Fail if the combination of ``columns`` has duplicate rows."""
    label = "+".join(columns)

    def _check(df: pd.DataFrame) -> CheckResult:
        dup_count = int(df.duplicated(subset=columns).sum())
        return CheckResult(
            name=f"unique[{label}]",
            passed=dup_count == 0,
            severity=severity,
            observed=dup_count,
            threshold=0,
            detail=f"{dup_count} duplicate row(s) on ({label})",
        )

    return _check


def in_set(column: str, allowed: set[str], severity: Severity = Severity.WARNING):
    """Fail if ``column`` contains values outside ``allowed``."""

    def _check(df: pd.DataFrame) -> CheckResult:
        present = set(df[column].dropna().unique())
        unexpected = present - allowed
        return CheckResult(
            name=f"in_set[{column}]",
            passed=len(unexpected) == 0,
            severity=severity,
            observed=len(unexpected),
            threshold=0,
            detail=f"unexpected values: {sorted(unexpected)}" if unexpected else "",
        )

    return _check


def row_count_at_least(minimum: int, severity: Severity = Severity.ERROR):
    """Fail if the DataFrame has fewer than ``minimum`` rows."""

    def _check(df: pd.DataFrame) -> CheckResult:
        n = len(df)
        return CheckResult(
            name="row_count_at_least",
            passed=n >= minimum,
            severity=severity,
            observed=n,
            threshold=minimum,
            detail=f"only {n} rows (expected >= {minimum})",
        )

    return _check


def build_default_suite() -> CheckSuite:
    """The suite pipeforge runs on the raw retail extract.

    Note the mix of ERROR and WARNING severities: nulls in key columns and
    negative quantities are treated as WARNINGs here because the bundled
    dataset intentionally contains a handful of dirty rows that the
    transform stage quarantines. Structural problems (missing invoice /
    stock code, empty dataset) are ERRORs that should abort a real run.
    """
    suite = CheckSuite(name="raw_orders")
    suite.add(row_count_at_least(100))
    suite.add(not_null("invoice_no", max_null_fraction=0.0, severity=Severity.ERROR))
    suite.add(not_null("stock_code", max_null_fraction=0.0, severity=Severity.ERROR))
    # Dirty-but-tolerated columns -> WARNING (quarantined downstream).
    suite.add(not_null("customer_id", max_null_fraction=0.05, severity=Severity.WARNING))
    suite.add(not_null("unit_price", max_null_fraction=0.05, severity=Severity.WARNING))
    suite.add(non_negative("quantity", severity=Severity.WARNING))
    suite.add(unique(["invoice_no", "stock_code", "invoice_date"], severity=Severity.WARNING))
    return suite
