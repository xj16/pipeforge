"""Command-line interface for pipeforge.

    python -m pipeforge run          # full ELT into the warehouse
    python -m pipeforge check        # data-quality checks only (no write)
    python -m pipeforge report       # print warehouse summary tables
    python -m pipeforge export       # write Snowflake/Databricks stubs

All commands are free and run locally against SQLite by default.
"""
from __future__ import annotations

import argparse
import sys

from .checks.core import CheckSuite
from .config import Config, WAREHOUSE_DIR, default_config
from .export import export_databricks_parquet, export_snowflake_ddl
from .generate_dataset import main as generate_dataset
from .pipeline.load import read_table
from .pipeline.run import PipelineError, run_pipeline, run_quality
from .pipeline.extract import extract_orders


def _ensure_dataset(config: Config) -> None:
    if not (config.raw_dir / "online_retail.csv").exists():
        print("Raw dataset missing -- generating it...")
        generate_dataset()


def cmd_run(config: Config) -> int:
    _ensure_dataset(config)
    print(f"pipeforge: running ELT into {config.describe()}")
    try:
        result = run_pipeline(config, load=True)
    except PipelineError as exc:
        print(f"\nPipeline aborted:\n{exc}", file=sys.stderr)
        return 1

    print("\nData-quality checks:")
    print(CheckSuite.summarize(result.check_results))

    print("\nWarehouse tables written:")
    for name, n in result.rows_written.items():
        print(f"  {name:<12} {n:>6} rows")

    print(f"\nQuarantined rows: {len(result.star.quarantine)}")
    print(f"Total revenue (fact_sales): {result.total_revenue:,.2f}")
    print("\nDone. Query it, e.g.:")
    print(f"  python -m pipeforge report")
    return 0


def cmd_check(config: Config) -> int:
    _ensure_dataset(config)
    raw = extract_orders(config.raw_dir)
    results = run_quality(raw)
    print(CheckSuite.summarize(results))
    blocking = CheckSuite.has_blocking_failure(results)
    print("\nBlocking failures:", "YES" if blocking else "none")
    return 1 if (blocking and config.fail_on_check_error) else 0


def cmd_report(config: Config) -> int:
    tables = ["dim_product", "dim_customer", "dim_date", "fact_sales"]
    for name in tables:
        try:
            df = read_table(name, config)
        except Exception as exc:  # table not created yet
            print(f"(could not read {name}: {exc}). Run `python -m pipeforge run` first.")
            return 1
        print(f"\n=== {name} ({len(df)} rows) ===")
        print(df.head(5).to_string(index=False))

    fact = read_table("fact_sales", config)
    product = read_table("dim_product", config)
    joined = fact.merge(product, on="product_key", how="left")
    by_cat = (
        joined.groupby("category")["revenue"].sum().sort_values(ascending=False)
    )
    print("\n=== revenue by category ===")
    print(by_cat.round(2).to_string())
    return 0


def cmd_export(config: Config) -> int:
    _ensure_dataset(config)
    result = run_pipeline(config, load=False)
    out = WAREHOUSE_DIR / "export"
    sf = export_snowflake_ddl(result.star, out)
    db = export_databricks_parquet(result.star, out)
    print(f"Snowflake DDL:      {sf}")
    print(f"Databricks bundle:  {db}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeforge", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the full ELT pipeline")
    sub.add_parser("check", help="run data-quality checks only")
    sub.add_parser("report", help="print warehouse summary")
    sub.add_parser("export", help="write Snowflake/Databricks export stubs")
    sub.add_parser("generate-data", help="(re)generate the bundled dataset")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = default_config()

    if args.command == "run":
        return cmd_run(config)
    if args.command == "check":
        return cmd_check(config)
    if args.command == "report":
        return cmd_report(config)
    if args.command == "export":
        return cmd_export(config)
    if args.command == "generate-data":
        generate_dataset()
        return 0
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
