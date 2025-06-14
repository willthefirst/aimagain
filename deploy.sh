#!/bin/bash

# VPS Deployment Script for FastAPI Chat Application
# This script pulls the latest Docker image and deploys it with proper configuration

set -e  # Exit on any error

# Default configuration - can be overridden by environment variables
CONTAINER_NAME="${CONTAINER_NAME:-chat-app}"
IMAGE_NAME="${IMAGE_NAME:-ghcr.io/$(git config --get remote.origin.url | sed 's/.*github.com[\/:]//g' | sed 's/\.git$//g')}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
HOST_PORT="${HOST_PORT:-8000}"
CONTAINER_PORT="${CONTAINER_PORT:-8000}"
DATA_DIR="${DATA_DIR:-/opt/chat-app-data}"

echo "=== FastAPI Application Deployment Script ==="
echo "Deployment started at: $(date)"
echo "Container name: $CONTAINER_NAME"
echo "Image: $IMAGE_NAME:$IMAGE_TAG"
echo "Port mapping: $HOST_PORT:$CONTAINER_PORT"
echo "Data directory: $DATA_DIR"

# Function to handle cleanup on exit
cleanup() {
    echo "=== Deployment Script Finished ==="
    echo "Completed at: $(date)"
}
trap cleanup EXIT

# Function to check if Docker is installed and running
check_docker() {
    echo "Checking Docker installation..."
    
    if ! command -v docker &> /dev/null; then
        echo "❌ ERROR: Docker is not installed"
        echo "Please install Docker first: https://docs.docker.com/engine/install/"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        echo "❌ ERROR: Docker daemon is not running"
        echo "Please start Docker service"
        exit 1
    fi
    
    echo "✅ Docker is installed and running"
}

# Function to setup data directory for SQLite persistence
setup_data_directory() {
    echo "Setting up data directory..."
    
    # Create data directory if it doesn't exist
    if [ ! -d "$DATA_DIR" ]; then
        echo "Creating data directory: $DATA_DIR"
        mkdir -p "$DATA_DIR"
    fi
    
    # Set proper permissions (adjust as needed for your setup)
    chmod 755 "$DATA_DIR"
    
    echo "✅ Data directory ready: $DATA_DIR"
}

# Function to stop and remove existing container
stop_existing_container() {
    echo "Checking for existing container: $CONTAINER_NAME"
    
    if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        echo "Stopping running container: $CONTAINER_NAME"
        docker stop "$CONTAINER_NAME"
    fi
    
    if docker ps -aq -f name="$CONTAINER_NAME" | grep -q .; then
        echo "Removing existing container: $CONTAINER_NAME"
        docker rm "$CONTAINER_NAME"
    fi
    
    echo "✅ Cleaned up existing container"
}

# Function to pull latest Docker image
pull_latest_image() {
    echo "Pulling latest Docker image: $IMAGE_NAME:$IMAGE_TAG"
    
    if docker pull "$IMAGE_NAME:$IMAGE_TAG"; then
        echo "✅ Successfully pulled latest image"
    else
        echo "❌ ERROR: Failed to pull Docker image"
        echo "Please check your image name and ensure you have access to the registry"
        exit 1
    fi
}

# Function to start new container
start_new_container() {
    echo "Starting new container: $CONTAINER_NAME"
    
    # Run container with proper configuration
    docker run -d \
        --name "$CONTAINER_NAME" \
        --restart unless-stopped \
        -p "$HOST_PORT:$CONTAINER_PORT" \
        -v "$DATA_DIR:/app/data" \
        -e PYTHONPATH=/app \
        --health-cmd="curl -f http://localhost:$CONTAINER_PORT/health || exit 1" \
        --health-interval=30s \
        --health-timeout=10s \
        --health-start-period=10s \
        --health-retries=3 \
        "$IMAGE_NAME:$IMAGE_TAG"
    
    if [ $? -eq 0 ]; then
        echo "✅ Container started successfully"
    else
        echo "❌ ERROR: Failed to start container"
        exit 1
    fi
}

# Function to verify deployment
verify_deployment() {
    echo "Verifying deployment..."
    
    # Wait for container to be ready
    echo "Waiting for application to start..."
    sleep 15
    
    # Check if container is running
    if ! docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        echo "❌ ERROR: Container is not running"
        echo "Container logs:"
        docker logs "$CONTAINER_NAME" || true
        exit 1
    fi
    
    # Check application health
    local max_attempts=6
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        echo "Health check attempt $attempt/$max_attempts..."
        
        if curl -f -s "http://localhost:$HOST_PORT/health" &> /dev/null; then
            echo "✅ Application is healthy and responding"
            return 0
        fi
        
        if [ $attempt -eq $max_attempts ]; then
            echo "❌ ERROR: Application health check failed after $max_attempts attempts"
            echo "Container logs:"
            docker logs --tail 50 "$CONTAINER_NAME" || true
            exit 1
        fi
        
        echo "Waiting 10 seconds before next attempt..."
        sleep 10
        ((attempt++))
    done
}

# Function to cleanup old Docker images
cleanup_old_images() {
    echo "Cleaning up old Docker images..."
    
    # Remove dangling images
    if docker images -f "dangling=true" -q | grep -q .; then
        docker rmi $(docker images -f "dangling=true" -q) 2>/dev/null || true
    fi
    
    # Remove old images of the same repository (keep last 3)
    local old_images=$(docker images "$IMAGE_NAME" --format "{{.ID}}" | tail -n +4)
    if [ -n "$old_images" ]; then
        echo "Removing old images..."
        echo "$old_images" | xargs -r docker rmi 2>/dev/null || true
    fi
    
    echo "✅ Cleanup completed"
}

# Function to show deployment status
show_status() {
    echo ""
    echo "=== Deployment Status ==="
    echo "Container status:"
    docker ps -f name="$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    
    echo ""
    echo "Application URL: http://localhost:$HOST_PORT"
    echo "Health check: http://localhost:$HOST_PORT/health"
    echo "Data directory: $DATA_DIR"
    
    echo ""
    echo "To view logs: docker logs -f $CONTAINER_NAME"
    echo "To stop: docker stop $CONTAINER_NAME"
    echo "To restart: docker restart $CONTAINER_NAME"
}

# Main deployment flow
main() {
    echo "🚀 Starting deployment process..."
    
    # Step 1: Check prerequisites
    check_docker
    
    # Step 2: Setup data directory
    setup_data_directory
    
    # Step 3: Stop existing container
    stop_existing_container
    
    # Step 4: Pull latest image
    pull_latest_image
    
    # Step 5: Start new container
    start_new_container
    
    # Step 6: Verify deployment
    verify_deployment
    
    # Step 7: Cleanup old images
    cleanup_old_images
    
    # Step 8: Show status
    show_status
    
    echo "🎉 Deployment completed successfully!"
}

# Run main function
main "$@" 