"""Tests for the star-schema transform."""
from __future__ import annotations

import pandas as pd

from pipeforge.schema.star import build_star_schema


def test_star_has_all_tables(raw_df):
    star = build_star_schema(raw_df)
    tables = star.tables()
    assert set(tables) == {"dim_product", "dim_customer", "dim_date", "fact_sales"}


def test_dimensions_have_unique_surrogate_keys(raw_df):
    star = build_star_schema(raw_df)
    assert star.dim_product["product_key"].is_unique
    assert star.dim_customer["customer_key"].is_unique
    assert star.dim_date["date_key"].is_unique


def test_dimensions_have_no_duplicate_business_keys(raw_df):
    star = build_star_schema(raw_df)
    assert star.dim_product["stock_code"].is_unique
    assert star.dim_customer["customer_id"].is_unique


def test_fact_foreign_keys_resolve(raw_df):
    """Every fact row must join to a real product, customer and date."""
    star = build_star_schema(raw_df)
    fact = star.fact_sales
    assert fact["product_key"].notna().all()
    assert fact["customer_key"].notna().all()
    assert set(fact["product_key"]).issubset(set(star.dim_product["product_key"]))
    assert set(fact["customer_key"]).issubset(set(star.dim_customer["customer_key"]))
    assert set(fact["date_key"]).issubset(set(star.dim_date["date_key"]))


def test_dirty_rows_are_quarantined(raw_df):
    star = build_star_schema(raw_df)
    # Generator injects: null customer_id, negative quantity, null unit_price.
    assert len(star.quarantine) >= 3
    reasons = set(star.quarantine["quarantine_reason"])
    assert "missing_customer_id" in reasons
    assert "missing_unit_price" in reasons
    assert "non_positive_quantity" in reasons


def test_no_dirty_rows_leak_into_fact(raw_df):
    star = build_star_schema(raw_df)
    fact = star.fact_sales
    assert (fact["quantity"] > 0).all()
    assert fact["unit_price"].notna().all()


def test_revenue_is_quantity_times_price(raw_df):
    star = build_star_schema(raw_df)
    fact = star.fact_sales
    expected = (fact["quantity"] * fact["unit_price"]).round(2)
    pd.testing.assert_series_equal(fact["revenue"], expected, check_names=False)


def test_date_dimension_flags_weekends(raw_df):
    star = build_star_schema(raw_df)
    dim = star.dim_date
    weekend_names = {"Saturday", "Sunday"}
    is_weekend = dim["weekday"].isin(weekend_names)
    pd.testing.assert_series_equal(
        dim["is_weekend"], is_weekend, check_names=False
    )
