"""Transform the cleaned retail extract into a Kimball-style star schema.

Output tables
-------------
dim_product   (product_key, stock_code, description, category, unit_price)
dim_customer  (customer_key, customer_id, country)
dim_date      (date_key, date, year, quarter, month, day, weekday, is_weekend)
fact_sales    (sale_id, product_key, customer_key, date_key,
               invoice_no, quantity, unit_price, revenue)

Rows that fail the "cleanable" bar (missing invoice/stock code, non-positive
quantity, missing price/customer/date) are quarantined into a separate frame
rather than silently dropped, so the run can report how much was rejected.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Static product catalogue used to enrich the fact rows with a category.
# In a real warehouse this would itself be a sourced dimension table.
PRODUCT_CATEGORY = {
    "SKU-001": "Kitchen",
    "SKU-002": "Kitchen",
    "SKU-003": "Stationery",
    "SKU-004": "Stationery",
    "SKU-005": "Home",
    "SKU-006": "Home",
    "SKU-007": "Electronics",
    "SKU-008": "Electronics",
    "SKU-009": "Electronics",
    "SKU-010": "Home",
}


@dataclass
class StarSchema:
    """The full set of warehouse tables plus the quarantined rows."""

    dim_product: pd.DataFrame
    dim_customer: pd.DataFrame
    dim_date: pd.DataFrame
    fact_sales: pd.DataFrame
    quarantine: pd.DataFrame

    def tables(self) -> dict[str, pd.DataFrame]:
        """Return only the warehouse tables (excludes quarantine)."""
        return {
            "dim_product": self.dim_product,
            "dim_customer": self.dim_customer,
            "dim_date": self.dim_date,
            "fact_sales": self.fact_sales,
        }

    def row_counts(self) -> dict[str, int]:
        counts = {name: len(df) for name, df in self.tables().items()}
        counts["quarantine"] = len(self.quarantine)
        return counts


def _split_valid(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partition rows into (valid, quarantined) with a reason column."""
    reasons = pd.Series("", index=df.index, dtype="object")

    def flag(mask: pd.Series, reason: str) -> None:
        nonlocal reasons
        hit = mask & (reasons == "")
        reasons = reasons.mask(hit, reason)

    flag(df["invoice_no"].isna(), "missing_invoice_no")
    flag(df["stock_code"].isna(), "missing_stock_code")
    flag(df["invoice_date"].isna(), "missing_or_bad_date")
    flag(df["customer_id"].isna(), "missing_customer_id")
    flag(df["unit_price"].isna(), "missing_unit_price")
    flag(df["quantity"].isna(), "missing_quantity")
    flag(df["quantity"].fillna(0) <= 0, "non_positive_quantity")

    bad_mask = reasons != ""
    valid = df.loc[~bad_mask].copy()
    quarantine = df.loc[bad_mask].copy()
    quarantine["quarantine_reason"] = reasons.loc[bad_mask]
    return valid, quarantine


def _build_dim_product(valid: pd.DataFrame) -> pd.DataFrame:
    dim = (
        valid[["stock_code", "description", "unit_price"]]
        .dropna(subset=["stock_code"])
        .drop_duplicates(subset=["stock_code"])
        .sort_values("stock_code")
        .reset_index(drop=True)
    )
    dim["category"] = dim["stock_code"].map(PRODUCT_CATEGORY).fillna("Uncategorised")
    dim.insert(0, "product_key", range(1, len(dim) + 1))
    return dim[["product_key", "stock_code", "description", "category", "unit_price"]]


def _build_dim_customer(valid: pd.DataFrame) -> pd.DataFrame:
    dim = (
        valid[["customer_id", "country"]]
        .dropna(subset=["customer_id"])
        .drop_duplicates(subset=["customer_id"])
        .sort_values("customer_id")
        .reset_index(drop=True)
    )
    dim.insert(0, "customer_key", range(1, len(dim) + 1))
    return dim[["customer_key", "customer_id", "country"]]


def _build_dim_date(valid: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(valid["invoice_date"]).dt.normalize().dropna().unique()
    dim = pd.DataFrame({"date": pd.to_datetime(sorted(dates))})
    dim["date_key"] = dim["date"].dt.strftime("%Y%m%d").astype(int)
    dim["year"] = dim["date"].dt.year
    dim["quarter"] = dim["date"].dt.quarter
    dim["month"] = dim["date"].dt.month
    dim["day"] = dim["date"].dt.day
    dim["weekday"] = dim["date"].dt.day_name()
    dim["is_weekend"] = dim["date"].dt.weekday >= 5
    return dim[
        ["date_key", "date", "year", "quarter", "month", "day", "weekday", "is_weekend"]
    ]


def _build_fact_sales(
    valid: pd.DataFrame,
    dim_product: pd.DataFrame,
    dim_customer: pd.DataFrame,
) -> pd.DataFrame:
    fact = valid.copy()
    fact["date_key"] = (
        pd.to_datetime(fact["invoice_date"]).dt.strftime("%Y%m%d").astype(int)
    )
    fact = fact.merge(
        dim_product[["product_key", "stock_code"]], on="stock_code", how="left"
    )
    fact = fact.merge(
        dim_customer[["customer_key", "customer_id"]], on="customer_id", how="left"
    )
    fact["quantity"] = fact["quantity"].astype("int64")
    fact["revenue"] = (fact["quantity"] * fact["unit_price"]).round(2)
    fact = fact.reset_index(drop=True)
    fact.insert(0, "sale_id", range(1, len(fact) + 1))
    return fact[
        [
            "sale_id",
            "product_key",
            "customer_key",
            "date_key",
            "invoice_no",
            "quantity",
            "unit_price",
            "revenue",
        ]
    ]


def build_star_schema(raw: pd.DataFrame) -> StarSchema:
    """Turn a raw extract into a validated star schema."""
    valid, quarantine = _split_valid(raw)

    dim_product = _build_dim_product(valid)
    dim_customer = _build_dim_customer(valid)
    dim_date = _build_dim_date(valid)
    fact_sales = _build_fact_sales(valid, dim_product, dim_customer)

    return StarSchema(
        dim_product=dim_product,
        dim_customer=dim_customer,
        dim_date=dim_date,
        fact_sales=fact_sales,
        quarantine=quarantine,
    )
