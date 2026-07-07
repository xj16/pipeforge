"""Tests for the parametrized dataset generator."""
from __future__ import annotations

from pipeforge.generate_dataset import (
    N_ORDERS,
    build,
    generate_rows,
    profile,
)
import random


def test_default_row_count_is_stable():
    rows = build()
    # N_ORDERS generated + 1 injected duplicate.
    assert len(rows) == N_ORDERS + 1


def test_generation_is_deterministic_for_a_seed():
    a = build(seed=123, rows=200)
    b = build(seed=123, rows=200)
    assert a == b


def test_rows_flag_scales_output():
    rows = build(rows=2000)
    assert len(rows) == 2001  # + injected duplicate


def test_revision_changes_c1003_country():
    base = {r["customer_id"]: r["country"] for r in build(revision=0)}
    revised = {r["customer_id"]: r["country"] for r in build(revision=1)}
    assert base["C-1003"] == "Germany"
    assert revised["C-1003"] != "Germany"
    # Other customers are untouched.
    assert revised["C-1001"] == base["C-1001"]


def test_injected_dirty_rows_present():
    rows = build()
    assert any(r["customer_id"] == "" for r in rows)  # missing customer
    assert any(str(r["quantity"]) == "-3" for r in rows)  # negative qty
    assert any(r["unit_price"] == "" for r in rows)  # missing price


def test_profile_reports_columns():
    out = profile(build(rows=100))
    assert "invoice_no" in out
    assert "distinct=" in out
    assert "nulls=" in out


def test_generate_rows_respects_n_orders():
    rows = generate_rows(random.Random(1), n_orders=50)
    assert len(rows) == 51  # + duplicate
