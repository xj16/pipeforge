"""Generate the bundled sample retail dataset.

We ship the CSVs in the repo (so the pipeline runs with zero network),
but this script regenerates them deterministically. The data mimics a
tiny "Online Retail"-style open dataset: orders of products by customers
across a handful of countries, deliberately seeded with a few dirty rows
(nulls, a negative quantity, a duplicate) so the data-quality checks have
something real to catch.

Usage::

    python -m pipeforge.generate_dataset                # default 600-row dataset
    python -m pipeforge.generate_dataset --rows 10000   # scale up
    python -m pipeforge.generate_dataset --revision 1   # move one customer's country
    python -m pipeforge.generate_dataset --profile      # print per-column stats

``--revision N`` changes customer ``C-1003``'s country (Germany -> a rotating
alternative) so a second run exercises the Type-2 slowly-changing dimension
and the ``merge`` load mode.
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

from .config import RAW_DIR

SEED = 20260707
N_ORDERS = 600

PRODUCTS = [
    # (stock_code, description, category, unit_price)
    ("SKU-001", "Ceramic Mug", "Kitchen", 8.50),
    ("SKU-002", "Steel Water Bottle", "Kitchen", 15.00),
    ("SKU-003", "Notebook A5", "Stationery", 4.25),
    ("SKU-004", "Gel Pen Pack", "Stationery", 6.75),
    ("SKU-005", "Desk Lamp", "Home", 29.90),
    ("SKU-006", "Cotton Tote Bag", "Home", 12.00),
    ("SKU-007", "Wireless Mouse", "Electronics", 19.99),
    ("SKU-008", "USB-C Cable", "Electronics", 9.49),
    ("SKU-009", "Bluetooth Speaker", "Electronics", 39.00),
    ("SKU-010", "Scented Candle", "Home", 11.25),
]

CUSTOMERS = [
    # (customer_id, country)
    ("C-1001", "United Kingdom"),
    ("C-1002", "United Kingdom"),
    ("C-1003", "Germany"),
    ("C-1004", "France"),
    ("C-1005", "Netherlands"),
    ("C-1006", "Germany"),
    ("C-1007", "Spain"),
    ("C-1008", "France"),
    ("C-1009", "Ireland"),
    ("C-1010", "United Kingdom"),
]

# Countries C-1003 rotates through on successive --revision values, so the
# SCD-2 logic has a real, deterministic change to detect between runs.
REVISION_COUNTRIES = ["Germany", "Austria", "Switzerland", "Belgium"]

START_DATE = date(2025, 1, 1)
DATE_SPAN_DAYS = 180


def _customers(revision: int) -> list[tuple[str, str]]:
    """Return the customer list, applying a --revision country change."""
    if revision <= 0:
        return list(CUSTOMERS)
    country = REVISION_COUNTRIES[revision % len(REVISION_COUNTRIES)]
    return [
        (cid, country if cid == "C-1003" else c) for cid, c in CUSTOMERS
    ]


def generate_rows(
    rng: random.Random, *, n_orders: int = N_ORDERS, revision: int = 0
) -> list[dict]:
    customers = _customers(revision)
    rows: list[dict] = []
    invoice_seq = 100000
    for _ in range(n_orders):
        invoice_seq += 1
        stock_code, description, _category, unit_price = rng.choice(PRODUCTS)
        customer_id, country = rng.choice(customers)
        order_day = START_DATE + timedelta(days=rng.randint(0, DATE_SPAN_DAYS))
        quantity = rng.randint(1, 12)
        rows.append(
            {
                "invoice_no": f"INV{invoice_seq}",
                "stock_code": stock_code,
                "description": description,
                "quantity": quantity,
                "unit_price": f"{unit_price:.2f}",
                "invoice_date": order_day.isoformat(),
                "customer_id": customer_id,
                "country": country,
            }
        )

    # --- deliberately inject a few dirty rows so DQ checks have work to do ---
    if rows:
        # A missing customer id (null dimension key).
        rows[5] = {**rows[5], "customer_id": ""}
        # A negative quantity (a return miscoded as a sale).
        rows[10] = {**rows[10], "quantity": -3}
        # A missing unit price.
        rows[15] = {**rows[15], "unit_price": ""}
        # An exact duplicate invoice line.
        rows.append(dict(rows[20]))
    return rows


def write_csv(rows: list[dict], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "invoice_no",
        "stock_code",
        "description",
        "quantity",
        "unit_price",
        "invoice_date",
        "customer_id",
        "country",
    ]
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def profile(rows: list[dict]) -> str:
    """Return a per-column null/min/max/distinct summary of the rows."""
    if not rows:
        return "(no rows)"
    cols = list(rows[0].keys())
    lines = [f"Profiled {len(rows)} rows across {len(cols)} columns:"]
    for col in cols:
        values = [r.get(col) for r in rows]
        non_null = [v for v in values if v not in (None, "")]
        nulls = len(values) - len(non_null)
        distinct = len(set(non_null))
        numeric = []
        for v in non_null:
            try:
                numeric.append(float(v))
            except (TypeError, ValueError):
                numeric = []
                break
        rng = (
            f" min={min(numeric):g} max={max(numeric):g}" if numeric else ""
        )
        lines.append(
            f"  {col:<14} nulls={nulls:<4} distinct={distinct:<5}{rng}"
        )
    return "\n".join(lines)


def build(
    *, rows: int = N_ORDERS, revision: int = 0, seed: int = SEED
) -> list[dict]:
    """Deterministically build the row list for the given parameters."""
    return generate_rows(random.Random(seed), n_orders=rows, revision=revision)


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(
        prog="pipeforge.generate_dataset",
        description="(Re)generate the bundled retail dataset.",
    )
    parser.add_argument("--rows", type=int, default=N_ORDERS, help="number of orders")
    parser.add_argument(
        "--revision",
        type=int,
        default=0,
        help="apply a customer country change (exercises SCD-2 / merge)",
    )
    parser.add_argument("--seed", type=int, default=SEED, help="RNG seed")
    parser.add_argument(
        "--profile",
        action="store_true",
        help="print per-column stats instead of (only) writing the CSV",
    )
    args = parser.parse_args(argv)

    rows = build(rows=args.rows, revision=args.revision, seed=args.seed)

    if args.profile:
        print(profile(rows))

    target = RAW_DIR / "online_retail.csv"
    write_csv(rows, target)
    print(f"Wrote {len(rows)} rows to {target}")
    return target


if __name__ == "__main__":
    main()
