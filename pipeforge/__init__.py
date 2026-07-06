"""pipeforge - a one-command local data-engineering playground.

A batch ELT pipeline over a bundled retail dataset: extract raw CSVs,
run data-quality checks, transform into a star schema, and load into
SQLite (default) or Postgres. Optional Airflow DAGs and a docker-compose
stack (Airflow + Postgres + Grafana) give the full experience, but the
core pandas pipeline runs and is tested without Docker.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
