"""Tests for the data-quality check layer."""
from __future__ import annotations

import pandas as pd

from pipeforge.checks import build_default_suite
from pipeforge.checks.core import CheckSuite, Severity
from pipeforge.checks.quality import (
    in_set,
    non_negative,
    not_null,
    row_count_at_least,
    unique,
)


def _df():
    return pd.DataFrame(
        {
            "a": [1, 2, 3, None],
            "b": [10, -5, 20, 30],
            "c": ["x", "x", "y", "z"],
        }
    )


def test_not_null_detects_nulls():
    res = not_null("a", max_null_fraction=0.0)(_df())
    assert not res.passed
    assert res.observed == 0.25


def test_not_null_respects_threshold():
    res = not_null("a", max_null_fraction=0.5)(_df())
    assert res.passed


def test_non_negative_flags_negatives():
    res = non_negative("b")(_df())
    assert not res.passed
    assert res.observed == 1


def test_unique_counts_duplicates():
    df = pd.DataFrame({"k": [1, 1, 2]})
    res = unique(["k"])(df)
    assert not res.passed
    assert res.observed == 1


def test_in_set_flags_unexpected():
    res = in_set("c", {"x", "y"})(_df())
    assert not res.passed
    assert res.observed == 1  # 'z' is unexpected


def test_row_count_at_least():
    assert row_count_at_least(3)(_df()).passed
    assert not row_count_at_least(10)(_df()).passed


def test_default_suite_no_blocking_failure_on_bundled_data(raw_df):
    """The bundled dataset's dirt is all WARNING-level -> nothing blocks."""
    results = build_default_suite().run(raw_df)
    assert not CheckSuite.has_blocking_failure(results)
    # But there ARE warning failures (negative qty + duplicate).
    warnings_failed = [r for r in results if not r.passed]
    assert any(r.severity is Severity.WARNING for r in warnings_failed)


def test_blocking_failure_when_key_column_null():
    df = pd.DataFrame(
        {
            "invoice_no": [None, "INV2"],
            "stock_code": ["S1", "S2"],
            "customer_id": ["C1", "C2"],
            "unit_price": [1.0, 2.0],
            "quantity": [1, 1],
            "invoice_date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
        }
    )
    # A null invoice_no is an ERROR-severity check.
    result = not_null("invoice_no", severity=Severity.ERROR)(df)
    assert result.is_blocking
