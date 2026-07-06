"""Extract stage: read raw CSV(s) into a typed pandas DataFrame.

The extract layer is intentionally lenient: it reads everything as-is and
normalises column names/whitespace, but does NOT drop bad rows. Cleaning
decisions belong to the transform stage, and *reporting* on bad data
belongs to the data-quality checks. This keeps the raw ("bronze") layer a
faithful copy of the source.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

RAW_COLUMNS = [
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "unit_price",
    "invoice_date",
    "customer_id",
    "country",
]


def extract_orders(raw_dir: Path, filename: str = "online_retail.csv") -> pd.DataFrame:
    """Read the bundled retail CSV into a DataFrame with normalised columns.

    Numeric and date columns are coerced with ``errors="coerce"`` so that
    malformed values become NaN/NaT rather than raising -- the downstream
    quality checks then surface exactly how many rows are affected.
    """
    path = Path(raw_dir) / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Raw dataset not found at {path}. "
            "Run `python -m pipeforge.generate_dataset` to create it."
        )

    df = pd.read_csv(path, dtype=str, keep_default_na=True)

    # Normalise column names (defensive: source headers may vary in case).
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Raw file is missing required columns: {missing}")

    # Trim whitespace on string columns.
    for col in ["invoice_no", "stock_code", "description", "customer_id", "country"]:
        df[col] = df[col].astype("string").str.strip()
        # Treat empty strings as missing.
        df[col] = df[col].replace({"": pd.NA})

    # Coerce numeric / date columns; bad values -> NaN/NaT (checked later).
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")

    return df[RAW_COLUMNS]
