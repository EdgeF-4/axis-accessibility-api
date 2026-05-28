# =============================================================================
# AXIS — production container image. Multi-stage so the final layer carries
# only the runtime (interpreter + wheels + app), not the build tooling.
# =============================================================================

# ---------- stage 1: install ----------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for: psycopg2 / asyncpg build, argon2-cffi, pgvector wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY alembic.ini ./

RUN pip install --upgrade pip \
 && pip install --prefix=/install .

# ---------- stage 2: runtime ----------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AXIS_ENV=production \
    AXIS_HOST=0.0.0.0 \
    AXIS_PORT=8000

# Run as a non-root user.
RUN groupadd -r axis && useradd -r -g axis -d /app -s /sbin/nologin axis

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --from=builder /app/src ./src
COPY --from=builder /app/alembic.ini ./alembic.ini

USER axis

EXPOSE 8000

# Healthcheck: liveness probe (cheap, no DB).
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz', timeout=2).read()" || exit 1

# Default: API. The worker entrypoint lands in Phase 4 alongside ARQ.
CMD ["uvicorn", "axis.main:app", "--host", "0.0.0.0", "--port", "8000"]
