"""Tests for the extract stage."""
from __future__ import annotations

import pandas as pd
import pytest

from pipeforge.pipeline.extract import RAW_COLUMNS, extract_orders


def test_extract_has_expected_columns(raw_df):
    assert list(raw_df.columns) == RAW_COLUMNS


def test_extract_coerces_types(raw_df):
    assert pd.api.types.is_integer_dtype(raw_df["quantity"])
    assert pd.api.types.is_float_dtype(raw_df["unit_price"])
    assert pd.api.types.is_datetime64_any_dtype(raw_df["invoice_date"])


def test_extract_preserves_all_rows(raw_df):
    # 600 generated + 1 duplicate injected = 601 rows (nothing dropped).
    assert len(raw_df) == 601


def test_extract_empty_strings_become_na(raw_df):
    # The generator injects a missing customer_id and a missing unit_price.
    assert raw_df["customer_id"].isna().sum() >= 1
    assert raw_df["unit_price"].isna().sum() >= 1


def test_extract_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_orders(tmp_path)
