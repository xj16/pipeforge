"""Tests for the static HTML warehouse explorer (the portfolio demo)."""
from __future__ import annotations

import html as htmlmod
import json
import re

from pipeforge.export.html_explorer import export_html, render_html
from pipeforge.pipeline.run import run_quality
from pipeforge.schema.star import build_star_schema


def _star_and_checks(raw_df):
    return build_star_schema(raw_df), run_quality(raw_df)


def test_render_html_is_self_contained(raw_df):
    star, checks = _star_and_checks(raw_df)
    page = render_html(star, checks)
    assert page.lstrip().lower().startswith("<!doctype html>")
    # No external hosts: no CDN scripts/styles/fonts anywhere.
    assert not re.search(r'src=["\']https?://', page)
    assert "cdn" not in page.lower()
    assert "<script" not in page.lower()  # dependency-free, no JS at all


def test_render_html_embeds_real_aggregates(raw_df):
    star, checks = _star_and_checks(raw_df)
    page = render_html(star, checks)
    embedded = re.search(r"<pre>(.*?)</pre>", page, re.S).group(1)
    agg = json.loads(htmlmod.unescape(embedded))

    expected_revenue = round(float(star.fact_sales["revenue"].sum()), 2)
    assert agg["total_revenue"] == expected_revenue
    assert agg["orders"] == len(star.fact_sales)
    assert agg["quarantined"] == len(star.quarantine)
    # Category + country rollups are present and non-empty.
    assert agg["by_category"] and agg["by_country"]
    assert len(agg["daily_revenue"]) >= 2


def test_render_html_has_all_charts_and_badges(raw_df):
    star, checks = _star_and_checks(raw_df)
    page = render_html(star, checks)
    assert page.count("<svg") >= 4  # donut, 2 bars, line
    assert "<polyline" in page  # daily-revenue line
    assert ">PASS<" in page or ">WARN<" in page  # DQ badges rendered


def test_export_html_writes_index(raw_df, tmp_path):
    star, checks = _star_and_checks(raw_df)
    out = export_html(star, checks, tmp_path)
    assert out.name == "index.html"
    assert out.exists() and out.stat().st_size > 5000


def test_render_html_escapes_labels():
    """A malicious category/country label must be HTML-escaped, not injected."""
    import pandas as pd

    from pipeforge.schema.star import StarSchema

    fact = pd.DataFrame(
        {
            "sale_id": [1],
            "product_key": [1],
            "customer_key": [1],
            "date_key": [20250101],
            "invoice_no": ["INV1"],
            "quantity": [1],
            "unit_price": [1.0],
            "revenue": [1.0],
        }
    )
    product = pd.DataFrame(
        {
            "product_key": [1],
            "stock_code": ["S"],
            "description": ["d"],
            "category": ["<script>alert(1)</script>"],
            "unit_price": [1.0],
        }
    )
    customer = pd.DataFrame(
        {
            "customer_key": [1],
            "customer_id": ["C1"],
            "country": ["UK"],
            "effective_from": [pd.Timestamp("1900-01-01").date()],
            "effective_to": [pd.NaT],
            "is_current": [True],
        }
    )
    date = pd.DataFrame(
        {
            "date_key": [20250101],
            "date": [pd.Timestamp("2025-01-01").date()],
            "year": [2025],
            "quarter": [1],
            "month": [1],
            "day": [1],
            "weekday": ["Wednesday"],
            "is_weekend": [False],
        }
    )
    star = StarSchema(product, customer, date, fact, quarantine=fact.iloc[0:0])
    page = render_html(star, [])
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
