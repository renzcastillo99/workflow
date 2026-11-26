# Apache Superset 6.1.0 (official image) + ONLY the missing pieces: Postgres driver + OAuth/OIDC client lib.
FROM apache/superset:latest
USER root
COPY wheels/ /tmp/wheels/
RUN uv pip install --python /app/.venv/bin/python --no-index --find-links /tmp/wheels psycopg2-binary authlib && rm -rf /tmp/wheels
USER superset
