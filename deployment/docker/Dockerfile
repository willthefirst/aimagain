# Use Python 3.11 slim base image for smaller footprint
FROM python:3.11-slim AS base

# Set environment variables for Python optimization
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies needed for SQLite and compilation
RUN apt-get update && apt-get install -y \
    sqlite3 \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory and data directory for SQLite persistence
WORKDIR /app
RUN mkdir -p /app/data

# Copy and install Python dependencies first for better Docker layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy application code
COPY . .

# Copy startup scripts and make them executable
COPY scripts/runtime/start.sh /app/start.sh
COPY scripts/runtime/start-dev.sh /app/start-dev.sh
RUN chmod +x /app/start.sh /app/start-dev.sh

# Create non-root user for security
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port 8000
EXPOSE 8000

# Health check to ensure the application is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use startup script that runs migrations before starting FastAPI
CMD ["/app/start.sh"]
