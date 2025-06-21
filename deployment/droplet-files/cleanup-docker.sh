#!/bin/bash

echo "🧹 Docker Cleanup Script"
echo "========================"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to show current Docker state
show_docker_state() {
    echo
    log "Current Docker containers:"
    docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}"

    echo
    log "Docker disk usage:"
    docker system df
}

# Main cleanup function
cleanup_docker() {
    log "Starting Docker cleanup..."

    # Stop all aimagain containers
    if docker ps -q --filter "name=aimagain" | grep -q .; then
        log "Stopping all aimagain containers..."
        docker stop $(docker ps -q --filter "name=aimagain") || true
        success "Stopped aimagain containers"
    fi

    # Remove all aimagain containers
    if docker ps -aq --filter "name=aimagain" | grep -q .; then
        log "Removing all aimagain containers..."
        docker rm -f $(docker ps -aq --filter "name=aimagain") || true
        success "Removed aimagain containers"
    fi

    # Remove dangling images
    if docker images -f "dangling=true" -q | grep -q .; then
        log "Removing dangling images..."
        docker rmi $(docker images -f "dangling=true" -q) || true
        success "Removed dangling images"
    fi

    # Prune system (removes unused containers, networks, images)
    log "Pruning Docker system..."
    docker system prune -f
    success "Docker system pruned"

    # Optional: Clean up volumes (be careful with this)
    # Uncomment the next lines if you want to clean up unused volumes
    # warning "Cleaning up unused volumes..."
    # docker volume prune -f
}

# Show current state
show_docker_state

echo
read -p "Do you want to proceed with cleanup? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    cleanup_docker
    echo
    log "Cleanup completed. New Docker state:"
    show_docker_state
else
    log "Cleanup cancelled."
fi
