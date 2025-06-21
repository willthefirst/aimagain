#!/bin/bash
set -e

echo "🚀 Starting zero-downtime deployment..."

# Function to update nginx upstream
update_nginx_upstream() {
    local port=$1
    sudo tee /etc/nginx/sites-available/aimagain.art << EOF
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
    sudo nginx -s reload
}

# Function to check health
check_health() {
    local port=$1
    local max_attempts=12
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        echo "Health check attempt $attempt/$max_attempts..."
        if curl -f http://localhost:$port/health &> /dev/null; then
            echo "✅ Instance on port $port is healthy!"
            return 0
        fi
        sleep 5
        attempt=$((attempt + 1))
    done

    echo "❌ Health check failed for port $port"
    return 1
}

# Determine current and new instances
if docker ps | grep -q "aimagain-blue.*8001"; then
    CURRENT="blue"
    NEW="green"
    CURRENT_PORT="8001"
    NEW_PORT="8002"
else
    CURRENT="green"
    NEW="blue"
    CURRENT_PORT="8002"
    NEW_PORT="8001"
fi

echo "📊 Current: $CURRENT (port $CURRENT_PORT)"
echo "🎯 Deploying: $NEW (port $NEW_PORT)"

# Pull latest image
docker pull ghcr.io/willthefirst/aimagain:latest

# Start new instance
docker-compose -f docker-compose.blue-green.yml up -d aimagain-$NEW

# Wait for new instance to be healthy
if check_health $NEW_PORT; then
    echo "🔄 Switching traffic to new instance..."
    update_nginx_upstream $NEW_PORT

    # Give it a moment to settle
    sleep 5

    # Verify the switch worked
    if check_health $NEW_PORT; then
        echo "🛑 Stopping old instance..."
        docker-compose -f docker-compose.blue-green.yml stop aimagain-$CURRENT
        docker-compose -f docker-compose.blue-green.yml rm -f aimagain-$CURRENT
        echo "🎉 Zero-downtime deployment completed!"
    else
        echo "🚨 New instance failed after traffic switch, rolling back..."
        update_nginx_upstream $CURRENT_PORT
        docker-compose -f docker-compose.blue-green.yml stop aimagain-$NEW
        docker-compose -f docker-compose.blue-green.yml rm -f aimagain-$NEW
        exit 1
    fi
else
    echo "🚨 New instance failed health check, aborting..."
    docker-compose -f docker-compose.blue-green.yml stop aimagain-$NEW
    docker-compose -f docker-compose.blue-green.yml rm -f aimagain-$NEW
    exit 1
fi
