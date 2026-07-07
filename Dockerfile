# Minimal image for the CORE pipeforge pipeline (no Airflow, no Grafana).
#
# Build + run the whole ELT in one command:
#     docker build -t pipeforge .
#     docker run --rm pipeforge run
#
# Or use the `demo` service in docker-compose.yml to build the static
# warehouse explorer and serve it at http://localhost:8000.
FROM python:3.11-slim

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt requirements-dev.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements-dev.txt

# Copy the source and install the package (provides the `pipeforge` console script).
COPY pipeforge ./pipeforge
COPY data ./data
RUN pip install --no-cache-dir -e .

# Default: run the full ELT into the bundled SQLite warehouse.
ENTRYPOINT ["python", "-m", "pipeforge"]
CMD ["run"]
