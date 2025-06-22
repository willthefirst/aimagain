# 🔧 Scripts directory

This directory contains scripts organized by purpose for better maintainability.

## 📁 Directory structure

```
scripts/
├── dev/                     # Development utilities
│   └── title_case_check.py # Code quality enforcement
├── runtime/                 # Application runtime scripts
│   └── start.sh           # Application startup script
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
