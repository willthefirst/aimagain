# 🔧 Scripts directory

This directory contains scripts organized by purpose for better maintainability.

## 📁 Directory structure

```
scripts/
├── dev/                     # Development utilities
│   └── title_case_check.py # Code quality enforcement
├── runtime/                 # Application runtime scripts
│   ├── start.sh            # Production startup script
│   └── start-dev.sh        # Development startup script with hot reloading
└── README.md              # This documentation
```

**Related scripts in other locations:**

- `deployment/scripts/` - Deployment-specific scripts

## 📋 Available scripts

### `deploy-copy-files.sh`

Manual SCP script to copy deployment files to a droplet server. This replaces the GitHub Actions `appleboy/scp-action` when the action isn't working properly.

**Location**: `deployment/scripts/deploy-copy-files.sh`

#### 🎯 **Quick usage**

```bash
# Using environment variables
export DROPLET_HOST="your.server.ip"
export DROPLET_USERNAME="deploy_user"
export DROPLET_SSH_KEY_PATH="~/.ssh/deploy_key"
./deployment/scripts/deploy-copy-files.sh

# Using command line flags
./deployment/scripts/deploy-copy-files.sh --host your.server.ip --username deploy_user --key-path ~/.ssh/deploy_key

# Show help
./deployment/scripts/deploy-copy-files.sh --help
```

#### 🏗️ **what it does**

- Copies all files from `deployment/droplet-files/` to `/opt/aimagain/deployment` on the remote server
- Equivalent to the GitHub Actions `appleboy/scp-action` with `strip_components: 2`
- Creates target directory if it doesn't exist
- Validates SSH key permissions and fixes them if needed
- Provides colored output for better visibility

#### 🔧 **Configuration OPTIONS**

**Environment Variables:**

- `DROPLET_HOST`: Server IP address or hostname
- `DROPLET_USERNAME`: SSH username for the server
- `DROPLET_SSH_KEY_PATH`: Path to SSH private key file

**Command line flags:**

- `--host, -h`: Server host (overrides env var)
- `--username, -u`: SSH username (overrides env var)
- `--key-path, -k`: SSH key path (overrides env var)
- `--help`: Show usage information

### `title_case_check.py`

Enforces sentence case for titles across the codebase, following the project's documentation standards.

#### 🎯 **Quick usage**

```bash
# Check all files for title case violations
python scripts/dev/title_case_check.py

# Auto-fix violations
python scripts/dev/title_case_check.py --fix

# Check specific directory
python scripts/dev/title_case_check.py templates/

# Check specific files
python scripts/dev/title_case_check.py README.md notes/
```

#### 🏗️ **supported file types**

- **Markdown files** (`.md`, `.markdown`): Headers (`# Title`, `## Subtitle`)
- **HTML files** (`.html`, `.htm`): Headers (`<h1>`, `<h2>`, etc.) and `<title>` tags
- **Jinja templates** (`.jinja`, `.jinja2`): HTML headers and `{% block title %}` blocks

#### 📝 **Exception handling**

**Line-level exceptions:**

```markdown
# This Title Will Be Ignored <!-- title-case-ignore -->
```

```html
<h1>API documentation</h1>
<!-- title-case-ignore -->
```

### `start.sh`

Application startup script used by Docker containers.

**Location**: `scripts/runtime/start.sh`

#### 🎯 **Purpose**

- Runs database migrations before starting the application
- Starts the FastAPI application with uvicorn
- Used as the CMD in Docker containers

#### 🏗️ **what it does**

1. **Migration check**: Runs Alembic migrations to ensure database is up to date
2. **Application startup**: Starts FastAPI with uvicorn on port 8000
3. **Health check compatibility**: Configures application for container health checks

### `start-dev.sh`

Development startup script with hot reloading and client-side LiveReload.

**Location**: `scripts/runtime/start-dev.sh`

#### 🎯 **Purpose**

- Runs database migrations before starting the development server
- Starts the FastAPI application with server-side hot reloading
- Launches a LiveReload server for client-side hot reloading
- Provides a complete development environment with automatic browser refresh

#### 🏗️ **what it does**

1. **Database setup**: Creates data directory and checks for database file
2. **Migration check**: Runs Alembic migrations to ensure database is up to date
3. **LiveReload server**: Starts a LiveReload server for client-side hot reloading
4. **Development server**: Starts FastAPI with uvicorn and hot reloading enabled

#### 🔥 **Hot reloading features**

**Server-side hot reloading (uvicorn):**

- Automatically restarts the FastAPI server when Python code changes
- Watches HTML template files for changes
- Includes debug logging and colored output

**Client-side hot reloading (LiveReload):**

- Automatically refreshes the browser when files change
- Watches template files (`src/templates/`)
- Watches source files (`src/`)
- Watches static files if they exist
- Runs on port 35729 (default)

#### 🔧 **Configuration**

**Environment variables:**

- `ENVIRONMENT`: Set to "development" automatically
- `LIVERELOAD_PORT`: LiveReload server port (default: 35729)

**File watching:**

- Templates: `src/templates/` (0.5s delay)
- Source files: `src/` (0.5s delay)
- Static files: `static/` (0.5s delay)

#### 📋 **Usage**

```bash
# Start development server with livereload
./scripts/runtime/start-dev.sh

# The script will:
# 1. ✅ setup database directory
# 2. ✅ run database migrations
# 3. 🔥 start livereload server on port 35729
# 4. 🔥 start FastAPI server on port 8000
```

**Accessing the application:**

- FastAPI server: http://localhost:8000
- LiveReload server: http://localhost:35729 (background service)

#### ⚡ **Live reload behavior**

**When you change files:**

- **Python files**: Server restarts automatically (uvicorn hot reload)
- **HTML templates**: Browser refreshes automatically (LiveReload)
- **CSS/JS files**: Browser refreshes automatically (LiveReload)

**Template integration:**

- LiveReload script is automatically injected into HTML templates
- Only active in development mode (`ENVIRONMENT=development`)
- Uses the base template's conditional inclusion

#### 🔄 **Process management**

- Runs LiveReload server as a background process
- Properly handles cleanup on script termination
- Kills background processes when stopping the server
- Graceful shutdown with process tracking
