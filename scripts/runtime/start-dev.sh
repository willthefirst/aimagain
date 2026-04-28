#!/bin/bash

# Development startup script for FastAPI application with hot reloading
# This script runs database migrations before starting the FastAPI server with --reload
# and also starts a LiveReload server for client-side hot reloading

set -e  # Exit on any error

# Function to handle cleanup on exit
cleanup() {
    if [[ -n "$LIVERELOAD_PID" ]]; then
        kill "$LIVERELOAD_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Function to check if database directory exists and create if needed
setup_database() {
    mkdir -p /app/data
}

# Function to run Alembic migrations
run_migrations() {
    if ! command -v alembic &> /dev/null; then
        echo "ERROR: Alembic command not found"
        exit 1
    fi

    if ! alembic -c config/alembic.ini upgrade head; then
        echo "❌ ERROR: Database migrations failed"
        exit 1
    fi
}

# Function to start LiveReload server for client-side hot reloading
start_livereload_server() {
    if ! command -v python &> /dev/null; then
        echo "WARNING: Python command not found, skipping LiveReload server"
        return 0
    fi

    # Set LiveReload port (default: 35729)
    export LIVERELOAD_PORT="${LIVERELOAD_PORT:-35729}"

    # Start LiveReload server in background
    # Watch templates, static files, and source files for changes
    python -c "
import logging
import time
import threading
from livereload import Server

# Silence per-connection / file-watch chatter from livereload + tornado.
# Use a filter (not setLevel) because livereload.serve() resets the level
# to INFO at startup, which would clobber a setLevel call.
class _DropBelowWarning(logging.Filter):
    def filter(self, record):
        return record.levelno >= logging.WARNING

_drop = _DropBelowWarning()
for name in ('livereload', 'tornado.access', 'tornado.application', 'tornado.general'):
    logging.getLogger(name).addFilter(_drop)

def start_server():
    server = Server()
    # Watch template files
    server.watch('src/templates/', delay=0.5)
    # Watch source files for template changes
    server.watch('src/', delay=0.5)
    # Watch static files if they exist
    server.watch('static/', delay=0.5)

    server.serve(port=${LIVERELOAD_PORT}, host='0.0.0.0', debug=False)

# Run server
start_server()
" &

    LIVERELOAD_PID=$!

    # Give LiveReload server a moment to start
    sleep 2
}

# Function to start FastAPI server with hot reloading
start_fastapi_dev() {
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
        --log-level info \
        --access-log \
        --use-colors
}

# Main execution flow
main() {
    setup_database
    run_migrations
    start_livereload_server
    echo "🔥 Dev server: http://0.0.0.0:8000 (hot reload + LiveReload on :$LIVERELOAD_PORT)"
    start_fastapi_dev
}

# Run main function
main "$@"
