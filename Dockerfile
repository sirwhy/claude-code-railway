# ─── Build stage ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for building native packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir poetry==1.8.3

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Export deps to requirements.txt (avoids poetry runtime overhead)
RUN poetry export -f requirements.txt --without-hashes --only main -o requirements.txt || \
    poetry export -f requirements.txt --without-hashes -o requirements.txt

# Add asyncpg (PostgreSQL driver) if not already listed
RUN grep -q asyncpg requirements.txt || echo "asyncpg>=0.29.0" >> requirements.txt

# Install into /install prefix
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Runtime stage ──────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# libpq runtime (needed by asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages
COPY --from=builder /install /usr/local

# Copy source code
COPY src/ ./src/
COPY config/ ./config/

# Create workspace directory (used as APPROVED_DIRECTORY)
RUN mkdir -p /workspace /data

# Non-root user for security
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app /workspace /data
USER botuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Railway injects PORT, but our bot uses polling (not HTTP), so no EXPOSE needed.
# If API server is enabled (ENABLE_API_SERVER=true), set PORT accordingly.
EXPOSE 8080

CMD ["python", "-m", "src.main"]
