#!/bin/bash
set -e

echo "🚀 Starting deployment..."

# Function to check if app is healthy
check_health() {
    local max_attempts=12  # 60 seconds total
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        echo "Health check attempt $attempt/$max_attempts..."
        if curl -f http://localhost:8000/health &> /dev/null; then
            echo "✅ Application is healthy!"
            return 0
        fi
        sleep 5
        attempt=$((attempt + 1))
    done

    echo "❌ Health check failed after $max_attempts attempts"
    return 1
}

# Automated version of manual process
docker pull ghcr.io/willthefirst/aimagain:latest
docker-compose down
docker-compose up -d

# Wait for health check
if check_health; then
    echo "🎉 Deployment completed successfully!"
else
    echo "🚨 Deployment failed, attempting rollback..."
    docker-compose down
    exit 1
fi
