#!/usr/bin/env python3
"""Development CLI."""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

DOCKER_COMPOSE_DEV_FILE = "docker-compose.dev.yml"
ENV_TEMPLATE = """# Development environment variables
# Copy this file to .env and customize as needed

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/app.db

# Application
# 32+ bytes required so JWT HMAC keys meet the SHA256 minimum
SECRET=dev-only-do-not-use-in-prod-aaaaaaaa
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Development — enables template auto-reload AND mounts the
# `/dev/login-as-seed-user` shortcut (see README "Dev auto-login").
ENVIRONMENT=development

# Seed user the dev-only `/dev/login-as-seed-user` route logs in as.
# Defaults to the admin user `dev seed` creates; uncomment + override
# to log in as a different seed-data user.
# DEV_LOGIN_EMAIL=admin@example.com
"""


def _resolve_project_root() -> Path:
    cwd = Path.cwd().resolve()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path(__file__).resolve().parent.parent


class CLIRunner:
    def __init__(self):
        self.project_root = _resolve_project_root()

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> int:
        if cwd is None:
            cwd = self.project_root

        print(f"🚀 Running: {' '.join(cmd)}")
        print(f"📁 Working directory: {cwd}")

        try:
            result = subprocess.run(cmd, cwd=cwd, check=False)
            return result.returncode
        except KeyboardInterrupt:
            print("\n⚠️ Interrupted by user")
            return 130
        except Exception as e:
            print(f"❌ Error running command: {e}")
            return 1

    def is_dev_container_running(self, service_name: str) -> bool:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                DOCKER_COMPOSE_DEV_FILE,
                "ps",
                "-q",
                service_name,
            ],
            capture_output=True,
            text=True,
            cwd=self.project_root,
        )
        return bool(result.stdout.strip())

    def wrap_for_compose(
        self, service_name: str, container_cmd: List[str]
    ) -> List[str]:
        """Use `exec` when the service is running; `run --rm --no-deps` otherwise."""
        if self.is_dev_container_running(service_name):
            return [
                "docker",
                "compose",
                "-f",
                DOCKER_COMPOSE_DEV_FILE,
                "exec",
                service_name,
                *container_cmd,
            ]
        print("ℹ️  Dev container not running — using one-off `docker compose run`")
        return [
            "docker",
            "compose",
            "-f",
            DOCKER_COMPOSE_DEV_FILE,
            "run",
            "--rm",
            "--no-deps",
            service_name,
            *container_cmd,
        ]

    def check_docker_installation(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "--version"], capture_output=True, text=True
            )
            if result.returncode != 0:
                print("❌ Docker is not installed or not accessible")
                print(
                    "Please install Docker Desktop: https://www.docker.com/products/docker-desktop"
                )
                return False
            print(f"✅ Docker found: {result.stdout.strip()}")
        except FileNotFoundError:
            print("❌ Docker is not installed or not accessible")
            print(
                "Please install Docker Desktop: https://www.docker.com/products/docker-desktop"
            )
            return False

        try:
            result = subprocess.run(
                ["docker", "compose", "version"], capture_output=True, text=True
            )
            if result.returncode != 0:
                print("❌ Docker Compose is not available")
                return False
            print(f"✅ Docker Compose found: {result.stdout.strip()}")
        except FileNotFoundError:
            print("❌ Docker Compose is not available")
            return False

        return True


class DevCommands:
    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def up(self, build: bool = False, detach: bool = False) -> int:
        print("🛠️ Starting development environment...")

        cmd = ["docker", "compose", "-f", DOCKER_COMPOSE_DEV_FILE, "up"]
        if build:
            cmd.append("--build")
        if detach:
            cmd.append("--detach")

        return self.runner.run_command(cmd)

    def down(self, volumes: bool = False) -> int:
        print("🛑 Stopping development environment...")

        cmd = ["docker", "compose", "-f", DOCKER_COMPOSE_DEV_FILE, "down"]
        if volumes:
            cmd.append("--volumes")

        return self.runner.run_command(cmd)

    def logs(self, follow: bool = False, service: Optional[str] = None) -> int:
        print("📋 Showing development environment logs...")

        cmd = ["docker", "compose", "-f", DOCKER_COMPOSE_DEV_FILE, "logs"]
        if follow:
            cmd.append("--follow")
        if service:
            cmd.append(service)

        return self.runner.run_command(cmd)

    def restart(self, service: Optional[str] = None) -> int:
        print("🔄 Restarting development environment...")

        cmd = ["docker", "compose", "-f", DOCKER_COMPOSE_DEV_FILE, "restart"]
        if service:
            cmd.append(service)

        return self.runner.run_command(cmd)


class TestCommands:
    # Tell pytest not to try collecting this class — the `Test` prefix
    # makes it look like a test class, but it's the CLI command handler.
    __test__ = False

    # Shortcut aliases for test paths. `dev test contract` expands to the full
    # path because `tests/test_contract` is excluded from default `pytest`
    # collection (`addopts` in `pyproject.toml`) and a regression in #100
    # showed the path is easy to forget.
    PATH_ALIASES = {"contract": "tests/test_contract"}

    def __init__(self, runner: CLIRunner, quality: "QualityCommands") -> None:
        self.runner = runner
        # `quality` is invoked as the test-loop pre-step (auto fmt, then
        # lint-gate) so a Black violation doesn't slip past `dev test` and
        # surface only at `dev lint` time. See issue #648 for the friction
        # this prevents. Injected (not constructed) so tests can stub the
        # pre-step without spawning real subprocesses.
        self.quality = quality

    def run_tests(
        self,
        verbose: bool = False,
        tb: Optional[str] = None,
        markers: Optional[str] = None,
        keywords: Optional[str] = None,
        paths: Optional[List[str]] = None,
        skip_lint: bool = False,
    ) -> int:
        # Inner-loop guard (#648). Default sequence: auto-fmt → lint →
        # pytest. Lint failures stop before pytest so the agent fixes
        # them once instead of running tests then re-running after the
        # lint surprise. `--skip-lint` is the escape hatch for the
        # "I know my code's dirty, I'm debugging a failing test" case.
        if not skip_lint:
            fmt_rc = self.quality.fmt()
            if fmt_rc != 0:
                print(
                    "❌ Formatter failed before tests could run. Fix the "
                    "underlying issue or re-run with `dev test --skip-lint` "
                    "to bypass the pre-step."
                )
                return fmt_rc
            lint_rc = self.quality.lint()
            if lint_rc != 0:
                print(
                    "❌ Lint failed before tests could run. Fix the "
                    "violations above or re-run with `dev test --skip-lint` "
                    "to bypass the pre-step."
                )
                return lint_rc

        print("🧪 Running tests...")

        cmd = ["pytest"]
        if verbose:
            cmd.append("-v")
        if tb:
            cmd.extend(["--tb", tb])
        if markers:
            cmd.extend(["-m", markers])
        if keywords:
            cmd.extend(["-k", keywords])
        if paths:
            cmd.extend(self.PATH_ALIASES.get(p, p) for p in paths)

        return self.runner.run_command(cmd)


class QualityCommands:
    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def lint(self) -> int:
        print("🔍 Running linting checks...")

        checks = [
            ("📝 Checking code formatting with black...", ["black", "--check", "."]),
            (
                "🔤 Checking import ordering with isort...",
                ["isort", "--check-only", "."],
            ),
            (
                "🏷️ Checking title case...",
                [sys.executable, "scripts/dev/title_case_check.py", "--check-only"],
            ),
            (
                "🔗 Checking template import boundaries...",
                [sys.executable, "scripts/dev/template_imports_check.py"],
            ),
            (
                "🐍 Checking Python cluster boundaries...",
                [sys.executable, "scripts/dev/python_cluster_imports_check.py"],
            ),
            (
                "🔗 Checking template route literals...",
                [sys.executable, "scripts/dev/template_route_check.py"],
            ),
        ]

        exit_code = 0
        for description, cmd in checks:
            print(description)
            result = self.runner.run_command(cmd)
            if result != 0:
                exit_code = result

        if exit_code == 0:
            print("✅ All linting checks passed!")
        else:
            print("❌ Some linting checks failed!")

        return exit_code

    def fmt(self) -> int:
        print("🎨 Applying formatters...")

        steps = [
            ("📝 Formatting code with black...", ["black", "."]),
            ("🔤 Sorting imports with isort...", ["isort", "."]),
        ]

        exit_code = 0
        for description, cmd in steps:
            print(description)
            result = self.runner.run_command(cmd)
            if result != 0:
                exit_code = result

        if exit_code == 0:
            print("✅ Formatting applied")
        else:
            print("❌ Formatting failed")

        return exit_code


class SeedCommands:
    SERVICE_NAME = "bedlam-connect-dev"

    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def seed(self) -> int:
        # `dev seed` runs in a one-off `docker compose run --no-deps` container
        # that bypasses start-dev.sh, so migrations must be applied explicitly
        # here — otherwise a freshly added revision crashes seed against a
        # stale schema with a raw OperationalError.
        from scripts.dev.migrate import run_alembic

        print("🧱 Applying migrations before seeding...")
        rc = run_alembic(
            self.runner,
            ["upgrade", "head"],
            mode="compose",
            service_name=self.SERVICE_NAME,
        )
        if rc != 0:
            print("❌ Migrations failed — aborting seed.")
            return rc

        print("🌱 Seeding fixture users...")
        seed_cmd = self.runner.wrap_for_compose(
            self.SERVICE_NAME, ["python", "scripts/dev/seed.py"]
        )
        return self.runner.run_command(seed_cmd)


class MigrateCommands:
    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def generate(self, message: str) -> int:
        from scripts.dev.migrate import generate

        return generate(self.runner, message)

    def up(self) -> int:
        from scripts.dev.migrate import up

        return up(self.runner)

    def down(self, steps: int) -> int:
        from scripts.dev.migrate import down

        return down(self.runner, steps)

    def roundtrip(self, scratch: Optional[str]) -> int:
        from scripts.dev.migrate import roundtrip

        return roundtrip(self.runner, scratch)


class PromoteAdminCommands:
    SERVICE_NAME = "bedlam-connect-dev"

    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def run(self, email: str, revoke: bool) -> int:
        container_cmd = ["python", "scripts/dev/promote_admin.py", email]
        if revoke:
            container_cmd.append("--revoke")
        cmd = self.runner.wrap_for_compose(self.SERVICE_NAME, container_cmd)
        return self.runner.run_command(cmd)


class RoutesCommands:
    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def list_routes(self, prefix: Optional[str] = None) -> int:
        """Print every HTTP route — surfaces router shadowing."""
        # Importing the FastAPI app evaluates all decorators, so DATABASE_URL
        # must be set. Use a local sqlite default to keep `dev routes`
        # runnable in a fresh checkout.
        import os
        import sys

        os.environ.setdefault(
            "DATABASE_URL", "sqlite+aiosqlite:///./data/dev_routes.db"
        )
        os.environ.setdefault("SECRET", "dev-routes-listing-only-aaaaaaaa")

        # `pip install -e .` exposes the `dev` console script but doesn't put
        # the project root on `sys.path` for arbitrary `from src...` imports.
        project_root = str(self.runner.project_root)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        try:
            from src.main import app
        except Exception as exc:
            print(f"❌ Failed to import src.main: {exc}")
            return 1

        rows: list[tuple[str, str, str]] = []
        for route in app.routes:
            methods = getattr(route, "methods", None)
            path = getattr(route, "path", None)
            endpoint = getattr(route, "endpoint", None)
            if not path or endpoint is None:
                continue
            if prefix and not path.startswith(prefix):
                continue
            method_str = ",".join(sorted(methods)) if methods else "?"
            handler = f"{endpoint.__module__}.{endpoint.__qualname__}"
            rows.append((path, method_str, handler))

        if not rows:
            scope = f" matching prefix '{prefix}'" if prefix else ""
            print(f"No routes found{scope}.")
            return 0

        # Group by first path segment.
        from collections import defaultdict

        by_prefix: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for path, method, handler in rows:
            segs = [s for s in path.split("/") if s]
            group = "/" + (segs[0] if segs else "")
            by_prefix[group].append((path, method, handler))

        method_w = max(len(r[1]) for r in rows)
        path_w = max(len(r[0]) for r in rows)
        for group in sorted(by_prefix):
            print(f"\n{group}")
            for path, method, handler in sorted(by_prefix[group]):
                print(f"  {method:<{method_w}}  {path:<{path_w}}  →  {handler}")

        print(f"\n{len(rows)} routes total.")
        return 0


class PlaywrightCommands:
    """One-time setup for the Playwright MCP server.

    The MCP entry in `.claude/settings.json` invokes
    `npx @playwright/mcp@latest`; that fetches and runs the server
    fresh each time without a pre-install step. The browser binary
    (Chromium) is the only thing that needs to be installed locally.
    This command runs `npx playwright install chromium` and prints
    the bookmark URL + a pointer to the auto-login route.
    """

    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def setup(self) -> int:
        print("🎭 Installing Chromium for Playwright (one-time, ~150MB)...")
        result = self.runner.run_command(
            ["npx", "--yes", "playwright", "install", "chromium"]
        )
        if result != 0:
            print(
                "❌ Chromium install failed. Confirm Node + npm are installed; "
                "see https://nodejs.org/."
            )
            return result

        print("\n✅ Playwright Chromium installed.")
        print("\nNext steps:")
        print("  1. Start the dev server:    dev up")
        print("  2. Seed the dev DB:         dev seed")
        print("  3. Log in (bookmark this):")
        print("       http://localhost:8000/dev/login-as-seed-user")
        print(
            "     Visiting it sets the session cookie for the seed admin user "
            "and redirects to /posts."
        )
        print(
            "\nClaude Code's Playwright MCP entry is already configured in "
            "`.claude/settings.json`. After restarting Claude Code, the agent "
            "can navigate / click / screenshot via the same auto-login URL."
        )
        return 0


class SetupCommands:
    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def setup(self) -> int:
        print("🔧 Setting up development environment...")

        if not self.runner.check_docker_installation():
            return 1

        dev_compose_file = self.runner.project_root / DOCKER_COMPOSE_DEV_FILE
        if not dev_compose_file.exists():
            print(f"❌ Development compose file not found: {dev_compose_file}")
            return 1
        print(f"✅ Development compose file found: {dev_compose_file}")

        env_file = self.runner.project_root / ".env"
        if not env_file.exists():
            print("📝 Creating .env template...")
            try:
                env_file.write_text(ENV_TEMPLATE)
                print(f"✅ Created .env template: {env_file}")
                print("   Please review and customize the values as needed")
            except Exception as e:
                print(f"❌ Failed to create .env file: {e}")
                return 1
        else:
            print(f"✅ Environment file found: {env_file}")

        print("\n🎉 Setup complete! You can now run:")
        print("   dev up        # Start development environment")
        print("   dev logs -f   # Follow logs")
        print("   dev test      # Run tests")

        return 0


class DevCLI:
    """Main CLI application."""

    def __init__(self):
        self.runner = CLIRunner()
        self.dev = DevCommands(self.runner)
        # `quality` is constructed first so it can be injected into
        # `TestCommands` (which runs fmt → lint as a pre-step before
        # pytest — see issue #648).
        self.quality = QualityCommands(self.runner)
        self.test = TestCommands(self.runner, self.quality)
        self.setup = SetupCommands(self.runner)
        self.seed_cmd = SeedCommands(self.runner)
        self.routes_cmd = RoutesCommands(self.runner)
        self.promote_admin_cmd = PromoteAdminCommands(self.runner)
        self.migrate_cmd = MigrateCommands(self.runner)
        self.playwright_cmd = PlaywrightCommands(self.runner)

    def create_parser(self) -> argparse.ArgumentParser:
        """Create the argument parser with all commands."""
        parser = argparse.ArgumentParser(
            description="Development CLI",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s setup               # Set up development environment
  %(prog)s up --build          # Start development environment with rebuild
  %(prog)s down                # Stop development environment
  %(prog)s logs -f             # Follow development logs
  %(prog)s test -m api         # Run API tests only
  %(prog)s test --tb short     # Run tests with short traceback
  %(prog)s lint                # Run all linting checks
            """,
        )

        subparsers = parser.add_subparsers(dest="command", help="Available commands")

        # Development commands (flattened for simplicity)
        self._add_up_parser(subparsers)
        self._add_down_parser(subparsers)
        self._add_logs_parser(subparsers)
        self._add_restart_parser(subparsers)

        # Other commands
        self._add_test_parser(subparsers)
        self._add_lint_parser(subparsers)
        self._add_fmt_parser(subparsers)
        self._add_setup_parser(subparsers)
        self._add_seed_parser(subparsers)
        self._add_routes_parser(subparsers)
        self._add_promote_admin_parser(subparsers)
        self._add_migrate_parser(subparsers)
        self._add_playwright_setup_parser(subparsers)

        return parser

    def _add_up_parser(self, subparsers):
        parser = subparsers.add_parser("up", help="Start development environment")
        parser.add_argument(
            "--build", action="store_true", help="Build images before starting"
        )
        parser.add_argument(
            "-d", "--detach", action="store_true", help="Run in detached mode"
        )
        parser.set_defaults(func=lambda args: self.dev.up(args.build, args.detach))

    def _add_down_parser(self, subparsers):
        parser = subparsers.add_parser("down", help="Stop development environment")
        parser.add_argument(
            "--volumes", action="store_true", help="Remove volumes as well"
        )
        parser.set_defaults(func=lambda args: self.dev.down(args.volumes))

    def _add_logs_parser(self, subparsers):
        parser = subparsers.add_parser("logs", help="Show development environment logs")
        parser.add_argument(
            "-f", "--follow", action="store_true", help="Follow log output"
        )
        parser.add_argument("service", nargs="?", help="Show logs for specific service")
        parser.set_defaults(func=lambda args: self.dev.logs(args.follow, args.service))

    def _add_restart_parser(self, subparsers):
        parser = subparsers.add_parser(
            "restart", help="Restart development environment"
        )
        parser.add_argument("service", nargs="?", help="Restart specific service")
        parser.set_defaults(func=lambda args: self.dev.restart(args.service))

    def _add_test_parser(self, subparsers):
        parser = subparsers.add_parser(
            "test",
            help="Run tests (auto-runs fmt + lint first; pass --skip-lint to bypass)",
            description=(
                "Run pytest. Each path may be a directory, file, or "
                "`file::testname` selector; pass several to run unrelated "
                "targets in one invocation. The literal token `contract` is "
                "a shortcut that expands to `tests/test_contract` — that "
                "directory is excluded from default collection (binds ports, "
                "needs a Playwright browser) and is easy to forget the path to."
                "\n\n"
                "By default this runs `dev fmt` then `dev lint` before "
                "pytest, so a Black/isort violation can't slip past tests "
                "and surface only at lint time (#648). On any lint failure "
                "pytest is not invoked. Pass --skip-lint to bypass the "
                "pre-step (useful when iterating on a failing test with "
                "intentionally messy code)."
            ),
        )
        parser.add_argument(
            "-v", "--verbose", action="store_true", help="Verbose output"
        )
        parser.add_argument(
            "--tb",
            choices=["short", "long", "line", "native", "no"],
            help="Traceback print mode",
        )
        parser.add_argument("-m", "--markers", help="Run tests with specific markers")
        parser.add_argument(
            "-k", "--keywords", help="Run tests matching keyword expressions"
        )
        parser.add_argument(
            "--skip-lint",
            action="store_true",
            help=(
                "Skip the auto fmt+lint pre-step and run pytest directly. "
                "Use when iterating on a failing test with intentionally "
                "dirty formatting."
            ),
        )
        parser.add_argument(
            "paths",
            nargs="*",
            help="One or more test paths or files (forwarded to pytest)",
        )
        parser.set_defaults(
            func=lambda args: self.test.run_tests(
                args.verbose,
                args.tb,
                args.markers,
                args.keywords,
                args.paths,
                args.skip_lint,
            )
        )

    def _add_lint_parser(self, subparsers):
        parser = subparsers.add_parser(
            "lint",
            help="Run linting checks",
            description=(
                "Run all linting checks: black, isort, title-case, "
                "template-import-boundaries, python-cluster-boundaries. "
                "Pre-commit hooks run the same checks automatically — "
                "don't bypass with --no-verify."
            ),
        )
        parser.set_defaults(func=lambda args: self.quality.lint())

    def _add_fmt_parser(self, subparsers):
        parser = subparsers.add_parser(
            "fmt",
            help="Auto-fix formatting (runs black and isort in write mode)",
            description=(
                "Auto-fix formatting in place by running `black .` and "
                "`isort .` in write mode. The natural pre-commit companion "
                "to `dev lint`."
            ),
        )
        parser.set_defaults(func=lambda args: self.quality.fmt())

    def _add_setup_parser(self, subparsers):
        parser = subparsers.add_parser(
            "setup",
            help="Set up development environment",
            description=(
                "First-time setup: creates `.env` from the template if "
                "missing and initializes the local database."
            ),
        )
        parser.set_defaults(func=lambda args: self.setup.setup())

    def _add_playwright_setup_parser(self, subparsers):
        parser = subparsers.add_parser(
            "playwright-setup",
            help="Install Chromium for the Playwright MCP server",
            description=(
                "One-time browser install for the Playwright MCP entry "
                "wired up in `.claude/settings.json`. Also prints the "
                "auto-login bookmark URL (`/dev/login-as-seed-user`) so "
                "the dev knows where to point their browser."
            ),
        )
        parser.set_defaults(func=lambda args: self.playwright_cmd.setup())

    def _add_seed_parser(self, subparsers):
        parser = subparsers.add_parser(
            "seed",
            help="Seed the dev database with fixture users",
            description=(
                "Apply any pending Alembic migrations, then seed the dev "
                "database with fixture users for manual testing. Migrations "
                "run first so a freshly added revision doesn't cause the "
                "seed to crash against a stale schema."
            ),
        )
        parser.set_defaults(func=lambda args: self.seed_cmd.seed())

    def _add_routes_parser(self, subparsers):
        parser = subparsers.add_parser(
            "routes",
            help="List every HTTP route registered on the app (catches shadowing)",
            description=(
                "Print every HTTP route registered on `src.main:app` grouped "
                "by path prefix. Surfaces router shadowing — two "
                "`include_router` calls registering handlers on overlapping "
                "paths — without spinning up the server."
            ),
        )
        parser.add_argument(
            "prefix",
            nargs="?",
            help="Filter by path prefix (e.g. /users)",
        )
        parser.set_defaults(func=lambda args: self.routes_cmd.list_routes(args.prefix))

    def _add_promote_admin_parser(self, subparsers):
        parser = subparsers.add_parser(
            "promote-admin",
            help="Grant or revoke admin (is_superuser) status for a user by email",
            description=(
                "Grant or revoke admin (`is_superuser`) status for a user "
                "matched by email. Idempotent — re-running with the same "
                "target is a no-op. Errors if no user matches (refuses to "
                "auto-create users on a typo). Runs inside the dev "
                "container. For the prod equivalent see the admin-"
                "bootstrapping section in `deployment/README.md`."
            ),
        )
        parser.add_argument("email", help="Email address of the user to (de)promote")
        parser.add_argument(
            "--revoke",
            action="store_true",
            help="Revoke admin status instead of granting it",
        )
        parser.set_defaults(
            func=lambda args: self.promote_admin_cmd.run(args.email, args.revoke)
        )

    def _add_migrate_parser(self, subparsers):
        parser = subparsers.add_parser(
            "migrate",
            help="Author and apply Alembic migrations against the host DB",
        )
        sub = parser.add_subparsers(dest="migrate_cmd")

        gen = sub.add_parser(
            "generate",
            help="alembic revision --autogenerate -m <message>",
            description=(
                "Generate a new Alembic revision via `--autogenerate` "
                "(host mode, requires `DATABASE_URL`). Review the generated "
                "file under `alembic/versions/` before applying — "
                "autogenerate isn't perfect at detection."
            ),
        )
        gen.add_argument("message", help="Revision message (required)")
        gen.set_defaults(func=lambda args: self.migrate_cmd.generate(args.message))

        up = sub.add_parser(
            "up",
            help="alembic upgrade head",
            description="Apply all pending Alembic migrations against the host DB.",
        )
        up.set_defaults(func=lambda args: self.migrate_cmd.up())

        down = sub.add_parser(
            "down",
            help="alembic downgrade -<N> (default N=1)",
            description="Reverse N migrations against the host DB. N defaults to 1.",
        )
        down.add_argument(
            "steps",
            nargs="?",
            type=int,
            default=1,
            help="Number of revisions to reverse (default 1)",
        )
        down.set_defaults(func=lambda args: self.migrate_cmd.down(args.steps))

        rt = sub.add_parser(
            "roundtrip",
            help="upgrade head → downgrade -1 → upgrade head against a scratch DB",
            description=(
                "Sanity-check a migration end-to-end against a throwaway "
                "sqlite DB at `/tmp/bedlam-migrate-roundtrip.db` (override "
                "with --scratch): upgrade head → downgrade -1 → upgrade "
                "head. Removes the scratch file on success; leaves it on "
                "failure for inspection. Never touches "
                "`data/bedlam-connect.db`."
            ),
        )
        rt.add_argument(
            "--scratch",
            default=None,
            help="Override scratch DB path (default /tmp/bedlam-migrate-roundtrip.db)",
        )
        rt.set_defaults(func=lambda args: self.migrate_cmd.roundtrip(args.scratch))

        def _print_help(_args):
            parser.print_help()
            return 1

        parser.set_defaults(func=_print_help)

    def run(self) -> int:
        """Run the CLI application."""
        parser = self.create_parser()
        args = parser.parse_args()

        if not args.command:
            parser.print_help()
            return 1

        if hasattr(args, "func"):
            return args.func(args)
        else:
            parser.print_help()
            return 1


def main() -> int:
    """Main entry point."""
    cli = DevCLI()
    return cli.run()


if __name__ == "__main__":
    sys.exit(main())
