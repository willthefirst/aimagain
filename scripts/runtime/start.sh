#!/bin/bash

# Startup script for FastAPI application with Alembic migrations
# This script runs database migrations before starting the FastAPI server

set -e  # Exit on any error

echo "=== FastAPI Application Startup ==="
echo "Starting at: $(date)"

# Function to handle cleanup on exit
cleanup() {
    echo "=== Application Shutdown ==="
    echo "Stopped at: $(date)"
}
trap cleanup EXIT

# Function to check if database directory exists and create if needed
setup_database() {
    echo "Setting up database directory..."
    mkdir -p /app/data

    # Check if database file exists, if not it will be created by migrations
    if [ ! -f "/app/data/aimagain.db" ]; then
        echo "Database file does not exist, will be created during migration"
    else
        echo "Database file found at /app/data/aimagain.db"
    fi
}

# Function to run Alembic migrations
run_migrations() {
    echo "Running Alembic migrations..."

    # Check if alembic command is available
    if ! command -v alembic &> /dev/null; then
        echo "ERROR: Alembic command not found"
        exit 1
    fi

    # Run migrations with error handling
    if alembic -c config/alembic.ini upgrade head; then
        echo "✅ Database migrations completed successfully"
    else
        echo "❌ ERROR: Database migrations failed"
        echo "Check your database connection and migration files"
        exit 1
    fi
}

# Function to start FastAPI server
start_fastapi() {
    echo "Starting FastAPI server..."
    echo "Server will be available at http://0.0.0.0:8000"

    # Check if uvicorn is available
    if ! command -v uvicorn &> /dev/null; then
        echo "ERROR: Uvicorn command not found"
        exit 1
    fi

    # Start uvicorn with production settings
    exec uvicorn src.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --workers 1 \
        --log-level info \
        --access-log \
        --use-colors
}

# Main execution flow
main() {
    echo "🚀 Initializing application startup sequence..."

    # Step 1: Setup database directory
    setup_database

    # Step 2: Run database migrations
    run_migrations

    # Step 3: Start FastAPI server
    start_fastapi
}

# Run main function
main "$@"
