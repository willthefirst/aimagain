# 🚀 Docker deployment guide

This guide covers the complete Docker containerization and CI/CD setup for the FastAPI Chat Application.

## 📋 Overview

The deployment setup includes:

- **Docker containerization** with optimized Python 3.11 image
- **GitHub Actions CI/CD** pipeline with automated deployments
- **VPS deployment** with SSH-based automation
- **SQLite persistence** with proper volume mounting
- **Health checks** and monitoring
- **Local development** environment with Docker Compose

## 🏗️ architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Developer     │    │   GitHub Actions │    │   VPS Server    │
│   Local Dev     │────┤   CI/CD Pipeline │────┤   Production    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                       │
         ▼                        ▼                       ▼
   Docker Compose          GitHub Container         Docker Runtime
   Development Env         Registry (ghcr.io)       Production Deploy
```

## 📁 File structure

```
├── Dockerfile              # Multi-stage container build
├── start.sh                # Container startup script with migrations
├── deploy.sh               # VPS deployment automation script
├── docker-compose.yml      # Local development environment
├── .dockerignore          # Build context optimization
├── .github/workflows/
│   └── deploy.yml         # CI/CD pipeline configuration
└── DEPLOYMENT.md          # This documentation
```

## 🐳 Dockerfile configuration

### Features:

- **Base image**: Python 3.11 slim for optimal size
- **Layer caching**: Optimized dependency installation
- **Security**: Non-root user execution
- **Health checks**: Built-in application monitoring
- **Database support**: SQLite with persistent storage
- **Migration handling**: Automatic Alembic migrations

### Build process:

1. Install system dependencies (SQLite, curl, gcc)
2. Create application directories with proper permissions
3. Install Python dependencies with pip caching
4. Copy application code and startup script
5. Configure non-root user for security
6. Set up health checks and startup command

## 🚀 Startup script (start.sh)

The startup script handles the complete application initialization:

### Process flow:

1. **Database setup**: Create data directory and check database file
2. **Migration execution**: Run `alembic upgrade head` with error handling
3. **Server startup**: Launch FastAPI with `uvicorn` in production mode
4. **Error handling**: Comprehensive logging and graceful failure handling

### Key features:

- ✅ Automatic database migrations before server start
- ✅ Comprehensive error logging and exit codes
- ✅ Health check integration
- ✅ Production-ready Uvicorn configuration

## 🔄 CI/CD pipeline (.github/workflows/deploy.yml)

The GitHub Actions workflow provides automated build and deployment:

### Workflow stages:

#### 1. build and push

- **Trigger**: Push to main branch or manual dispatch
- **Registry**: GitHub Container Registry (ghcr.io)
- **Tags**: `latest`, commit SHA, branch name
- **Features**: Multi-platform build, layer caching, metadata extraction

#### 2. deploy to vps

- **Dependency**: Successful build completion
- **Method**: SSH connection to VPS server
- **Process**: Download and execute deployment script
- **Verification**: Health check validation

### Required secrets:

- `HOST`: VPS server IP address or hostname
- `USERNAME`: SSH username for VPS access
- `SSH_KEY`: Private SSH key for authentication

## 🖥️ vps deployment script (deploy.sh)

The deployment script automates the complete deployment process on the VPS:

### Deployment steps:

1. **Prerequisites check**: Verify Docker installation and service status
2. **Data directory setup**: Create and configure persistent storage
3. **Container management**: Stop and remove existing containers
4. **Image management**: Pull latest image from registry
5. **Container startup**: Launch new container with proper configuration
6. **Health verification**: Validate application startup and response
7. **Cleanup**: Remove old images to save disk space
8. **Status report**: Display deployment status and useful commands

### Configuration OPTIONS:

```bash
# Environment variables for customization
CONTAINER_NAME="chat-app"          # Container name
IMAGE_NAME="ghcr.io/user/repo"    # Docker image URL
IMAGE_TAG="latest"                 # Image tag to deploy
HOST_PORT="8000"                   # Host port mapping
DATA_DIR="/opt/chat-app-data"      # Data persistence directory
```

## 🔧 Local development (docker-compose.yml)

Docker Compose provides a complete local development environment:

### Services:

- **chat-app**: FastAPI application with live code reloading
- **Network**: Isolated development network
- **Volumes**: Persistent database and source code mounting

### Development features:

- 🔄 **Live reloading**: Code changes reflected immediately
- 📁 **Volume mounting**: Database persistence and source code access
- 🌐 **Port mapping**: Application available at `http://localhost:8000`
- 🔍 **Health checks**: Built-in monitoring and status reporting

## 📋 Setup instructions

### 1. local development setup

```bash
# Clone the repository
git clone <your-repo-url>
cd <your-repo-name>

# Create local data directory
mkdir -p data

# Start development environment
docker-compose up --build

# Access application
open http://localhost:8000
```

### 2. GitHub repository setup

1. **Enable GitHub Container Registry**:

   - Go to repository Settings → Actions → General
   - Enable "Read and write permissions" for GITHUB_TOKEN

2. **Add deployment secrets**:

   ```
   HOST: your-vps-ip-address
   USERNAME: your-vps-username
   SSH_KEY: your-private-ssh-key
   ```

3. **Configure repository access**:
   - Ensure repository is public or configure GHCR access for private repos

### 3. vps server setup

1. **Install Docker**:

   ```bash
   # Ubuntu/Debian
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker $USER
   ```

2. **Create deployment directory**:

   ```bash
   sudo mkdir -p /opt/chat-app
   sudo chown $USER:$USER /opt/chat-app
   ```

3. **Configure SSH access**:

   - Add your public SSH key to `~/.ssh/authorized_keys`
   - Ensure SSH service is running and accessible

4. **Initial deployment** (optional):
   ```bash
   # Manual first deployment
   cd /opt/chat-app
   curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/deploy.sh -o deploy.sh
   chmod +x deploy.sh
   ./deploy.sh
   ```

## 🔍 Monitoring and maintenance

### Health checks

The application includes built-in health monitoring:

- **Endpoint**: `http://localhost:8000/health`
- **Docker health checks**: Automatic container health monitoring
- **Deployment verification**: Post-deployment health validation

### Logging

```bash
# View application logs
docker logs -f chat-app

# View deployment logs
docker logs chat-app --since=1h

# Container status
docker ps -f name=chat-app
```

### Database management

```bash
# Access SQLite database
docker exec -it chat-app sqlite3 /app/data/chat_app.db

# Backup database
docker cp chat-app:/app/data/chat_app.db ./backup-$(date +%Y%m%d).db

# View migration status
docker exec -it chat-app alembic current
```

## 🛠️ troubleshooting

### Common issues and solutions:

#### 1. build failures

```bash
# Check Docker build logs
docker build --no-cache .

# Verify dependencies
pip install -e .
```

#### 2. deployment failures

```bash
# Check vps Docker status
docker info

# Verify image accessibility
docker pull ghcr.io/YOUR_USERNAME/YOUR_REPO:latest

# Check container logs
docker logs chat-app
```

#### 3. database issues

```bash
# Check database file permissions
ls -la /opt/chat-app-data/

# Run migrations manually
docker exec -it chat-app alembic upgrade head

# Reset database (caution: data loss)
docker exec -it chat-app rm /app/data/chat_app.db
docker restart chat-app
```

#### 4. network connectivity

```bash
# Test application health
curl http://localhost:8000/health

# Check port availability
netstat -tlnp | grep 8000

# Verify firewall settings
sudo ufw status
```

## 🔄 Updating the application

### Automatic updates (recommended)

Push changes to the main branch, and GitHub Actions will automatically:

1. Build new Docker image
2. Push to registry
3. Deploy to VPS
4. Verify deployment

### Manual updates

```bash
# On vps server
cd /opt/chat-app
./deploy.sh
```

## 📊 Production considerations

### Security

- ✅ Non-root container execution
- ✅ Minimal base image (Python slim)
- ✅ Secure SSH key authentication
- ✅ Private registry access control

### Performance

- ✅ Multi-stage Docker builds
- ✅ Layer caching optimization
- ✅ Health check monitoring
- ✅ Automatic old image cleanup

### Scalability

- 🔄 Ready for load balancer integration
- 🔄 Database migration to PostgreSQL when needed
- 🔄 Horizontal scaling with container orchestration
- 🔄 Environment-specific configuration

## 📚 Additional resources

- [Docker best practices](https://docs.docker.com/develop/dev-best-practices/)
- [GitHub Actions documentation](https://docs.github.com/en/actions)
- [FastAPI deployment guide](https://fastapi.tiangolo.com/deployment/)
- [Alembic migration guide](https://alembic.sqlalchemy.org/en/latest/tutorial.html)

---

**💡 Tip**: Start with local development using `docker-compose up`, then proceed with CI/CD setup once you're satisfied with the local configuration.
