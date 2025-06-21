# 🚀 Continuous deployment implementation plan

## 🎯 Overview

Evolution from manual Docker deployment to zero-downtime continuous deployment on DigitalOcean droplet.

**Current State**: Manual SSH + `docker pull` + `docker run` commands
**Target State**: Push to main → Automatic zero-downtime deployment

## 📋 Implementation phases

### **Phase 1: Foundation Setup** ✅ **COMPLETED**

**Goal**: Switch to Docker Compose + Improved Deploy Script
**Risk**: None - Service stays running throughout
**Time**: 1-2 hours

#### Step 1.1: Create Docker Compose File ✅

Create `/opt/aimagain/docker-compose.yml`:

```yaml
version: '3.8'
services:
  aimagain:
    image: ghcr.io/willthefirst/aimagain:latest
    container_name: aimagain-app
    restart: unless-stopped
    ports:
      - '8000:8000'
    volumes:
      - ./data:/app/data
    env_file:
      - config/.env
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8000/health']
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

**Test**: `docker-compose up -d` works exactly like manual commands
**Rollback**: `docker-compose down` + back to manual `docker run`

#### Step 1.2: Create Basic Deployment Script ✅

Create `/opt/aimagain/deploy.sh`:

```bash
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
```

**Test**: `./deploy.sh` works manually
**Rollback**: Run manual commands if script fails

---

### **Phase 2: automation** ✅ **COMPLETED**

**Goal**: GitHub Actions Integration
**Risk**: Low - Only triggers after successful build
**Time**: 1 hour

#### Step 2.1: Set Up SSH Access ✅

On droplet:

```bash
# Generate ssh key for GitHub actions
ssh-keygen -t ed25519 -f ~/.ssh/github_actions_key -N ""
cat ~/.ssh/github_actions_key.pub >> ~/.ssh/authorized_keys
```

Add to GitHub Secrets:

- `DROPLET_HOST`: Droplet IP address
- `DROPLET_USERNAME`: Username (root/user)
- `DROPLET_SSH_KEY`: Content of `~/.ssh/github_actions_key`

#### Step 2.2: Update GitHub Actions Workflow ✅

Update `.github/workflows/build-and-push.yml`:

```yaml
name: Build and Deploy

# ... existing build job ...

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    steps:
      - name: Deploy to DigitalOcean Droplet
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.DROPLET_HOST }}
          username: ${{ secrets.DROPLET_USERNAME }}
          key: ${{ secrets.DROPLET_SSH_KEY }}
          script: |
            cd /opt/aimagain
            ./deploy.sh
```

**Test**: Push small change to main, watch GitHub Actions
**Rollback**: Current container keeps running if deployment fails

---

### **Phase 3: Load Balancing Foundation**

**Goal**: Add Nginx Reverse Proxy
**Risk**: Low - App still accessible on port 8000 if Nginx fails
**Time**: 1-2 hours

#### Step 3.1: Install and Configure Nginx ✅ **ALREADY DONE**

**Note**: Nginx already installed with SSL/HTTPS working for aimagain.art domain!
**Enhancement**: Add upstream block for blue-green switching capability

```bash
# Nginx already installed and working

# Create configuration
sudo tee /etc/nginx/sites-available/aimagain << 'EOF'
upstream aimagain_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;  # Replace with domain/IP

    location / {
        proxy_pass http://aimagain_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Connection settings for reliability
        proxy_connect_timeout 5s;
        proxy_send_timeout 10s;
        proxy_read_timeout 10s;
        proxy_next_upstream error timeout invalid_header http_500 http_502 http_503;
    }
}
EOF

# Enable the site
sudo ln -s /etc/nginx/sites-available/aimagain /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl start nginx
```

**Test**: Access app through Nginx (port 80) instead of direct port 8000
**Rollback**: App still accessible on port 8000

#### Step 3.2: Prepare Blue-Green Infrastructure

Create `/opt/aimagain/docker-compose.blue-green.yml`:

```yaml
version: '3.8'
services:
  aimagain-blue:
    image: ghcr.io/willthefirst/aimagain:latest
    container_name: aimagain-blue
    restart: unless-stopped
    ports:
      - '8001:8000'
    volumes:
      - ./data:/app/data
    env_file:
      - config/.env
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8000/health']
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  aimagain-green:
    image: ghcr.io/willthefirst/aimagain:latest
    container_name: aimagain-green
    restart: unless-stopped
    ports:
      - '8002:8000'
    volumes:
      - ./data:/app/data
    env_file:
      - config/.env
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8000/health']
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

**Test**: Just create the file, don't use yet
**Rollback**: Delete file if needed

---

### **Phase 4: Zero-Downtime infrastructure**

**Goal**: Blue-Green Deployment Setup
**Risk**: Medium - More complex, but with automatic rollback
**Time**: 2-3 hours

#### Step 4.1: Create Zero-Downtime Deployment Script

Create `/opt/aimagain/deploy-zero-downtime.sh`:

```bash
#!/bin/bash
set -e

echo "🚀 Starting zero-downtime deployment..."

# Function to update nginx upstream
update_nginx_upstream() {
    local port=$1
    sudo tee /etc/nginx/sites-available/aimagain << EOF
upstream aimagain_backend {
    server 127.0.0.1:$port;
}

server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://aimagain_backend;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_connect_timeout 5s;
        proxy_send_timeout 10s;
        proxy_read_timeout 10s;
        proxy_next_upstream error timeout invalid_header http_500 http_502 http_503;
    }
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
```

#### Step 4.2: Migrate to Blue-Green

```bash
# Stop current container
docker-compose down

# Start blue instance
docker-compose -f docker-compose.blue-green.yml up -d aimagain-blue

# Update nginx to point to port 8001
```

#### Step 4.3: Update GitHub Actions

Change deployment script in workflow:

```yaml
script: |
  cd /opt/aimagain
  ./deploy-zero-downtime.sh
```

**Test**: Deploy change and verify zero downtime
**Rollback**: Switch back to `./deploy.sh`

---

## 🎯 **Problem-Solution mapping**

| Phase       | Problem Solved             | User Experience                              |
| ----------- | -------------------------- | -------------------------------------------- |
| **Phase 1** | Manual deployment toil     | Still brief downtime, but reliable           |
| **Phase 2** | Manual trigger requirement | Still brief downtime, but automatic          |
| **Phase 3** | Direct app exposure        | Still brief downtime, but better reliability |
| **Phase 4** | Service interruption       | **Zero downtime** - seamless updates         |

## 🚨 **Emergency rollback plan**

If anything goes wrong at any phase:

```bash
cd /opt/aimagain

# Stop all containers
docker-compose down
docker-compose -f docker-compose.blue-green.yml down

# Go back to manual process
docker run --env-file config/.env -v ./data:/app/data -p 8000:8000 ghcr.io/willthefirst/aimagain:latest
```

## 📊 **Monitoring during transition**

- **Deployment logs**: `./deploy.sh 2>&1 | tee deployment.log`
- **Health monitoring**: `watch -n 5 curl -s http://localhost/health`
- **GitHub Actions**: Monitor workflow runs for failures

## 🔄 **Implementation timeline**

- **Week 1**: Phase 1 (Foundation)
- **Week 2**: Phase 2 (Automation)
- **Week 3**: Phase 3 (Nginx Setup)
- **Week 4**: Phase 4 (Zero-Downtime)

## ✅ **Success criteria**

- **Phase 1**: Can deploy with `./deploy.sh` instead of manual commands
- **Phase 2**: Push to main automatically deploys to droplet
- **Phase 3**: App accessible through Nginx on port 80
- **Phase 4**: Deployments complete with zero user-facing downtime

## 📝 **Notes**

- Each phase builds on the previous and can be stopped at any point
- Service stays running throughout entire implementation
- Clear rollback strategy at every step
- Health checks prevent bad deployments from going live
