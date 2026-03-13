FROM python:3.12-slim AS base
WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

FROM base AS builder
COPY pyproject.toml .
RUN pip install --no-cache-dir build && pip install --no-cache-dir ".[dev]" 2>/dev/null; \
    pip install --no-cache-dir .

FROM base AS production
# Non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY pyproject.toml .

# Install package in-place (editable)
RUN pip install --no-cache-dir -e . --no-deps

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# entrypoint runs migrations then starts server
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
ENTRYPOINT ["/docker-entrypoint.sh"]
