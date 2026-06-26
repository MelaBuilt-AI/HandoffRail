# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY server/pyproject.toml ./
RUN pip install --no-cache-dir ".[prod]"

# ── Runtime stage ────────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies (including prod extras for asyncpg)
COPY server/pyproject.toml ./
RUN pip install --no-cache-dir ".[prod]"

# Copy application code
COPY server/app ./app
COPY server/alembic.ini ./alembic.ini
COPY server/alembic ./alembic

# Create non-root user for security
RUN groupadd -r handoffrail && useradd -r -g handoffrail handoffrail
RUN mkdir -p /app/data && chown handoffrail:handoffrail /app/data

USER handoffrail

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]