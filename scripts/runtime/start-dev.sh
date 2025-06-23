#!/bin/bash

# Development startup script for FastAPI application with hot reloading
# This script runs database migrations before starting the FastAPI server with --reload
# and also starts a LiveReload server for client-side hot reloading

set -e  # Exit on any error

echo "=== FastAPI Development Server Startup ==="
echo "Starting at: $(date)"

# Function to handle cleanup on exit
cleanup() {
    echo "=== Development Server Shutdown ==="
    echo "Killing background processes..."

    # Kill LiveReload server if it's running
    if [[ -n "$LIVERELOAD_PID" ]]; then
        kill "$LIVERELOAD_PID" 2>/dev/null || true
        echo "LiveReload server stopped"
    fi

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

# Function to start LiveReload server for client-side hot reloading
start_livereload_server() {
    echo "Starting LiveReload server for client-side hot reloading..."

    # Check if python is available for LiveReload
    if ! command -v python &> /dev/null; then
        echo "WARNING: Python command not found, skipping LiveReload server"
        return 0
    fi

    # Set LiveReload port (default: 35729)
    export LIVERELOAD_PORT="${LIVERELOAD_PORT:-35729}"

    # Start LiveReload server in background
    # Watch templates, static files, and source files for changes
    python -c "
import time
import threading
from livereload import Server

def start_server():
    server = Server()
    # Watch template files
    server.watch('src/templates/', delay=0.5)
    # Watch source files for template changes
    server.watch('src/', delay=0.5)
    # Watch static files if they exist
    server.watch('static/', delay=0.5)

    print(f'🔥 LiveReload server starting on port ${LIVERELOAD_PORT}')
    server.serve(port=${LIVERELOAD_PORT}, host='0.0.0.0', debug=False)

# Run server
start_server()
" &

    LIVERELOAD_PID=$!
    echo "🔥 LiveReload server started (PID: $LIVERELOAD_PID) on port $LIVERELOAD_PORT"

    # Give LiveReload server a moment to start
    sleep 2
}

# Function to start FastAPI server with hot reloading
start_fastapi_dev() {
    echo "Starting FastAPI development server with hot reloading..."
    echo "🔥 Hot reloading enabled for both API and templates"
    echo "🔥 Client-side LiveReload enabled for browser auto-refresh"
    echo "Server will be available at http://0.0.0.0:8000"

    # Check if uvicorn is available
    if ! command -v uvicorn &> /dev/null; then
        echo "ERROR: Uvicorn command not found"
        exit 1
    fi

    # Set environment variables for development
    export ENVIRONMENT="development"
    export LIVERELOAD_PORT="${LIVERELOAD_PORT:-35729}"

    # Start uvicorn with development settings including hot reloading
    exec uvicorn src.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --reload \
        --reload-include="*.html" \
        --log-level debug \
        --access-log \
        --use-colors
}

# Main execution flow
main() {
    echo "🚀 Initializing development server startup sequence..."

    # Step 1: Setup database directory
    setup_database

    # Step 2: Run database migrations
    run_migrations

    # Step 3: Start LiveReload server for client-side hot reloading
    start_livereload_server

    # Step 4: Start FastAPI development server with hot reloading
    start_fastapi_dev
}

# Run main function
main "$@"
