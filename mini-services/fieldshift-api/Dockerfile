# CropTwist API — FastAPI + SQLAlchemy 2 on PostgreSQL 16 / PostGIS 3.5.
#
# Multi-stage build pinned to python:3.12-slim (matches the sandbox runtime,
# CPython 3.12.16). All 48 pinned requirements ship manylinux cp312 wheels
# (rasterio bundles GDAL/GEOS/PROJ, ortools bundles its C++ runtime,
# psycopg2-binary bundles libpq), so no apt build chain is needed.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Isolated venv so the runtime stage can copy the exact dependency tree.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Dedicated non-root user for the API process.
RUN groupadd --system --gid 10001 croptwist \
 && useradd --system --uid 10001 --gid croptwist --home-dir /app --shell /usr/sbin/nologin croptwist

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
# Application code + Alembic migration set (the compose entrypoint runs
# `alembic upgrade head` before uvicorn; migrations/env.py reads
# CROPTWIST_DATABASE_URL via app.core.config).
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

RUN chown -R croptwist:croptwist /app

USER croptwist

EXPOSE 3030

# Liveness probe without curl/wget: stdlib urllib against /api/v1/health.
# (Readiness incl. the PostGIS check is /api/v1/health/ready.)
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request as u; r = u.urlopen('http://127.0.0.1:3030/api/v1/health', timeout=4); sys.exit(0 if r.status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3030"]
