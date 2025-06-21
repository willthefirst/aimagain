#!/bin/bash

echo "🧪 Deployment Test Script"
echo "========================="

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

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Test functions
test_docker_compose() {
    log "Testing docker-compose configuration..."
    if docker-compose -f docker-compose.blue-green.yml config > /dev/null 2>&1; then
        success "Docker-compose configuration is valid"
        return 0
    else
        error "Docker-compose configuration has errors"
        return 1
    fi
}

test_health_endpoint() {
    local port=$1
    log "Testing health endpoint on port $port..."
    if curl -f -s http://localhost:$port/health > /dev/null 2>&1; then
        success "Health endpoint responding on port $port"
        return 0
    else
        warning "Health endpoint not responding on port $port (this is expected if no service is running)"
        return 1
    fi
}

show_current_state() {
    log "Current running containers:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

    echo
    log "Nginx configuration test:"
    if sudo nginx -t; then
        success "Nginx configuration is valid"
    else
        error "Nginx configuration has issues"
    fi

    echo
    log "Testing health endpoints:"
    test_health_endpoint 8001
    test_health_endpoint 8002
}

# Run tests
log "Starting deployment system tests..."
echo

# Test 1: Docker compose configuration
test_docker_compose

echo

# Test 2: Show current state
show_current_state

echo

# Test 3: Check if scripts are executable
log "Checking script permissions..."
for script in "deploy-zero-downtime.sh" "deploy-zero-downtime-improved.sh" "cleanup-docker.sh"; do
    if [ -f "$script" ]; then
        if [ -x "$script" ]; then
            success "$script is executable"
        else
            warning "$script is not executable, making it executable..."
            chmod +x "$script"
        fi
    else
        warning "$script not found in current directory"
    fi
done

echo
log "Test completed. Review the results above."
echo
log "Next steps:"
echo "  1. Run './cleanup-docker.sh' if you need to clean up Docker state"
echo "  2. Run './deploy-zero-downtime-improved.sh' to test the improved deployment"
echo "  3. Compare with './deploy-zero-downtime.sh' (original) if needed"
