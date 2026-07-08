FROM python:3.13-slim AS builder
WORKDIR /app

# APP_VERSION busts the dependency layer on every new build so `pip install`
# re-resolves to the latest versions allowed by pyproject.toml — new images
# automatically pick up dependency updates instead of reusing a cached layer.
ARG APP_VERSION=dev

# All dependencies ship binary wheels (psycopg[binary] bundles libpq) —
# no compiler or -dev packages needed.
COPY pyproject.toml .
COPY src/ src/
# Production install — no dev/test dependencies in the runtime image.
RUN echo "Building KryptoSkatt ${APP_VERSION}" \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --upgrade .

FROM python:3.13-slim AS production
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY pyproject.toml .

COPY --chmod=0755 docker-entrypoint.sh /docker-entrypoint.sh
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
ENTRYPOINT ["/docker-entrypoint.sh"]
