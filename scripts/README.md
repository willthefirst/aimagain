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
├── dev_cli.py              # Development CLI for common tasks
├── __init__.py             # Python package initialization
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

- Copies all files from `deployment/droplet-files/` to `/opt/bedlam-connect/deployment` on the remote server
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

### `dev_cli.py` — the `dev` command

Single source of truth for the project's developer commands. Installed as the `dev` console script entry point via `pip install -e .` (see `pyproject.toml`).

This is the canonical reference for `dev` commands. **All other docs should link here, not restate the command list** (see [`../CLAUDE.md`](../CLAUDE.md) for the rule).

#### Available commands

Run `dev --help` for the live, authoritative list. As of this writing:

| Command | What it does |
| --- | --- |
| `dev setup` | First-time setup: creates `.env`, initializes the local database. |
| `dev up [--build] [-d]` | Start the Docker Compose development environment (optionally rebuild images, optionally detach). |
| `dev down [--volumes]` | Stop the development environment (optionally drop volumes). |
| `dev logs [-f] [service]` | Show logs from the dev environment, optionally following or scoped to one service. |
| `dev restart [service]` | Restart the whole dev environment or a single service. |
| `dev test [-v] [--tb MODE] [-m MARKERS] [-k KEYWORDS] [path ...]` | Run pytest. Each `path` can be a directory, a file, or a `file::testname` selector; pass several to run unrelated targets in one invocation. |
| `dev lint` | Run black, isort, autoflake, and the title-case checker. Pre-commit runs the same checks automatically. |
| `dev fmt` | Auto-fix formatting in place by running `black .` and `isort .` in write mode. The natural pre-commit companion to `dev lint`. |
| `dev seed` | Apply any pending Alembic migrations, then seed the dev database with fixture users for manual testing. Migrations run first so a freshly added revision doesn't cause the seed to crash against a stale schema. |
| `dev routes [prefix]` | Print every HTTP route registered on `src.main:app` grouped by path prefix. Surfaces router shadowing — two `include_router` calls registering handlers on overlapping paths — without spinning up the server. |
| `dev promote-admin <email> [--revoke]` | Grant or revoke admin (`is_superuser`) status for a user matched by email. Idempotent. Errors if no user matches. Runs inside the dev container. For the prod equivalent see [`deployment/README.md`](../deployment/README.md#bootstrapping-an-admin). |
| `dev migrate generate "<message>"` | Generate a new Alembic revision via `--autogenerate` (host mode, requires `DATABASE_URL`). Review the generated file under `alembic/versions/` before applying. |
| `dev migrate up` | Apply all pending Alembic migrations against the host DB (`alembic upgrade head`). |
| `dev migrate down [N]` | Reverse `N` migrations against the host DB. `N` defaults to 1. |
| `dev migrate roundtrip [--scratch <path>]` | Sanity-check a migration end-to-end against a throwaway sqlite DB at `/tmp/bedlam-migrate-roundtrip.db` (override with `--scratch`): upgrade head → downgrade -1 → upgrade head. Removes the scratch file on success; leaves it on failure for inspection. Never touches `data/aimagain.db`. |

For per-command flag details, run `dev <command> --help`.

Recommended local workflow: write code → `dev fmt` → `dev test`.

#### Installation

```bash
pip install -e .
dev --help
```

Without `pip install -e .`, the CLI is also runnable directly: `python3 scripts/dev_cli.py <command>` or `./scripts/dev_cli.py <command>`.

#### Tests <!-- title-case-ignore -->

Tests for `scripts/dev/*` live colocated as `scripts/dev/test_*.py`, matching the `src/<layer>/test_*.py` pattern in [`../CLAUDE.md`](../CLAUDE.md). Pytest discovers them via the `scripts` entry in `pyproject.toml`'s `testpaths`. Run only the dev CLI tests with `dev test scripts/dev`.

### `dev/promote_admin.py`

Async script that flips `is_superuser` on a user matched by email. Used by `dev promote-admin` (local) and `deployment/droplet-files/promote-admin.sh` (production). Idempotent — re-running with the same target value is a no-op. Refuses to auto-create users on a typo (would silently mint a ghost admin).

Tests: [`../tests/test_promote_admin.py`](../tests/test_promote_admin.py).

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
