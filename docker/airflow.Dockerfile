# Airflow image with pipeforge and its deps installed.
FROM apache/airflow:2.9.3-python3.11

# Install pipeforge's runtime deps (pinned via constraints already in image).
COPY requirements.txt /tmp/pipeforge-requirements.txt
RUN pip install --no-cache-dir -r /tmp/pipeforge-requirements.txt

# The package itself is bind-mounted at /opt/airflow/pipeforge by compose,
# and /opt/airflow is on PYTHONPATH, so `import pipeforge` just works.
