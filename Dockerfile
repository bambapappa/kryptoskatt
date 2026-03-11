# =============================================================================
# Stage 1: Builder - Install dependencies
# =============================================================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Install dependencies
RUN pip install --no-cache-dir ".[dev]"

# =============================================================================
# Stage 2: Runtime - Application container
# =============================================================================
FROM python:3.12-slim-bookworm AS runtime

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=appuser:appgroup pyproject.toml /home/appuser/
COPY --chown=appuser:appgroup src/ /home/appuser/src/
COPY --chown=appuser:appgroup alembic.ini /home/appuser/
COPY --chown=appuser:appgroup alembic/ /home/appuser/alembic/
COPY --chown=appuser:appgroup startup.sh /home/appuser/startup.sh
RUN chmod +x /home/appuser/startup.sh

# Copy price history CSVs if present (optional — directory may be empty or absent)
COPY --chown=appuser:appgroup PriceHistory/ /home/appuser/PriceHistory/

# Set working directory
WORKDIR /home/appuser

# Add local src to Python path (must come before site-packages)
ENV PYTHONPATH="/home/appuser/src:${PYTHONPATH}"

# Switch to non-root user
WORKDIR /home/appuser

# Switch to non-root user
USER appuser

# Expose port for web server
EXPOSE 8000

# Default command: run migrations then start web server
CMD ["/home/appuser/startup.sh"]
