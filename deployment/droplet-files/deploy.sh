#!/bin/bash
set -e

echo "🚀 Starting zero-downtime deployment..."

# Colors for better output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to run commands with stderr redirected to stdout
run_cmd() {
    "$@" 2>&1
}

# Function to clean up containers
cleanup_containers() {
    local service_name=$1
    log "Cleaning up existing containers for $service_name..."

    # Stop any running containers with this name
    if docker ps -q --filter "name=$service_name" | grep -q .; then
        log "Stopping running $service_name containers..."
        run_cmd docker stop $(docker ps -q --filter "name=$service_name") || true
    fi

    # Remove any containers with this name
    if docker ps -aq --filter "name=$service_name" | grep -q .; then
        log "Removing $service_name containers..."
        run_cmd docker rm -f $(docker ps -aq --filter "name=$service_name") || true
    fi

    # Clean up any orphaned containers that might conflict
    if docker ps -aq --filter "name=.*$service_name" | grep -q .; then
        log "Removing any orphaned containers matching $service_name pattern..."
        run_cmd docker rm -f $(docker ps -aq --filter "name=.*$service_name") || true
    fi
}

# Function to update nginx upstream
update_nginx_upstream() {
    local port=$1
    log "Updating nginx configuration to point to port $port..."

    sudo tee /etc/nginx/sites-available/aimagain.art > /dev/null << EOF
upstream aimagain_backend {
    server 127.0.0.1:$port;
}

server {
    server_name aimagain.art www.aimagain.art;

    location / {
        proxy_pass http://aimagain_backend;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Enhanced reliability settings
        proxy_connect_timeout 5s;
        proxy_send_timeout 10s;
        proxy_read_timeout 10s;
        proxy_next_upstream error timeout invalid_header http_500 http_502 http_503;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/aimagain.art/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/aimagain.art/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if (\$host = aimagain.art) {
        return 301 https://\$host\$request_uri;
    } # managed by Certbot

    listen 80;
    server_name aimagain.art www.aimagain.art;
    return 404; # managed by Certbot
}
EOF

    # Test nginx configuration before reloading
    if run_cmd sudo nginx -t; then
        sudo nginx -s reload
        success "Nginx configuration updated and reloaded successfully"
    else
        error "Nginx configuration test failed!"
        return 1
    fi
}

# Function to check health
check_health() {
    local port=$1
    local max_attempts=12
    local attempt=1

    log "Starting health checks for port $port..."
    while [ $attempt -le $max_attempts ]; do
        log "Health check attempt $attempt/$max_attempts..."
        if curl -f -s http://localhost:$port/health > /dev/null 2>&1; then
            success "Instance on port $port is healthy!"
            return 0
        fi
        sleep 5
        attempt=$((attempt + 1))
    done

    error "Health check failed for port $port after $max_attempts attempts"
    return 1
}

# Function to rollback deployment
rollback() {
    local old_port=$1
    local failed_service=$2

    error "Deployment failed! Rolling back..."

    # Switch nginx back to old instance
    if update_nginx_upstream $old_port; then
        success "Nginx rolled back to port $old_port"
    else
        error "Failed to rollback nginx configuration!"
    fi

    # Clean up failed instance
    cleanup_containers "aimagain-$failed_service"

    error "Rollback completed. System is running on port $old_port"
}

get_current_port() {
    if [ -f /etc/nginx/sites-available/aimagain.art ]; then
        grep "server 127.0.0.1:" /etc/nginx/sites-available/aimagain.art | sed 's/.*127.0.0.1:\([0-9]*\);.*/\1/' || echo "none"
    else
        echo "none"
    fi
}

# Determine current and new instances based on nginx configuration
CURRENT_PORT=$(get_current_port)
log "Nginx is currently configured for port: $CURRENT_PORT"

if [ "$CURRENT_PORT" = "8001" ]; then
    CURRENT="blue"
    NEW="green"
    NEW_PORT="8002"
elif [ "$CURRENT_PORT" = "8002" ]; then
    CURRENT="green"
    NEW="blue"
    NEW_PORT="8001"
else
    # No current instance configured, default to blue
    warning "No current nginx configuration detected. Starting with blue instance."
    CURRENT="none"
    NEW="blue"
    CURRENT_PORT="none"
    NEW_PORT="8001"
fi

log "Current: $CURRENT (port $CURRENT_PORT)"
log "Deploying: $NEW (port $NEW_PORT)"

# Clean up any existing containers for the new instance
cleanup_containers "aimagain-$NEW"

# Pull latest image
log "Pulling latest Docker image..."
if run_cmd docker pull ghcr.io/willthefirst/aimagain:latest; then
    success "Docker image pulled successfully"
else
    error "Failed to pull Docker image"
    exit 1
fi

# Start new instance
log "Starting new $NEW instance..."
if run_cmd docker-compose -f docker-compose.blue-green.yml up -d aimagain-$NEW; then
    success "Started aimagain-$NEW container"
else
    error "Failed to start aimagain-$NEW container"
    exit 1
fi

# Wait for new instance to be healthy
if check_health $NEW_PORT; then
    log "Switching traffic to new instance..."
    if update_nginx_upstream $NEW_PORT; then
        # Give it a moment to settle
        sleep 5

        # Verify the switch worked
        if check_health $NEW_PORT; then
            success "Traffic successfully switched to $NEW instance"

            # Only stop old instance if there was one
            if [ "$CURRENT" != "none" ]; then
                log "Stopping old $CURRENT instance..."
                run_cmd docker-compose -f docker-compose.blue-green.yml stop aimagain-$CURRENT || true
                run_cmd docker-compose -f docker-compose.blue-green.yml rm -f aimagain-$CURRENT || true
                success "Old $CURRENT instance stopped and removed"
            fi

            success "🎉 Zero-downtime deployment completed successfully!"
            log "New instance ($NEW) is running on port $NEW_PORT"
        else
            # Rollback if verification fails
            if [ "$CURRENT" != "none" ]; then
                rollback $CURRENT_PORT $NEW
            else
                error "New instance failed verification and no fallback available!"
            fi
            exit 1
        fi
    else
        error "Failed to update nginx configuration"
        cleanup_containers "aimagain-$NEW"
        exit 1
    fi
else
    error "New instance failed health check, aborting deployment"
    cleanup_containers "aimagain-$NEW"
    exit 1
fi
