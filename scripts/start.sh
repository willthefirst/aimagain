#!/bin/bash

# Startup script for the chat application
# This script ensures database migrations are run before starting the app

set -e

echo "🚀 Starting chat application..."

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ]; then
    echo "⚠️  DATABASE_URL not set, using default SQLite database"
    export DATABASE_URL="sqlite+aiosqlite:///./chat_app.db"
fi

echo "📊 Database URL: $DATABASE_URL"

# Run database migrations
echo "🔄 Running database migrations..."
alembic upgrade head

if [ $? -eq 0 ]; then
    echo "✅ Database migrations completed successfully"
else
    echo "❌ Database migrations failed"
    exit 1
fi

# Start the application
echo "🌟 Starting FastAPI application..."
exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" --reload="${RELOAD:-false}"
