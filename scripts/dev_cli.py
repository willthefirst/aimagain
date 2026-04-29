#!/usr/bin/env python3
"""
Development CLI.

This CLI provides convenient commands for common development tasks.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# Constants
DOCKER_COMPOSE_DEV_FILE = "docker-compose.dev.yml"
ENV_TEMPLATE = """# Development environment variables
# Copy this file to .env and customize as needed

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/app.db

# Application
DEBUG=true
# 32+ bytes required so JWT HMAC keys meet the SHA256 minimum
SECRET=dev-only-do-not-use-in-prod-aaaaaaaa

# Development
DEVELOPMENT=true
"""


class CLIRunner:
    """Handles command execution and common utilities."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> int:
        """Run a command and return its exit code."""
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

    def check_docker_installation(self) -> bool:
        """Check if Docker and Docker Compose are available."""
        # Check Docker
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

        # Check Docker Compose
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
    """Development environment commands."""

    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def up(self, build: bool = False, detach: bool = False) -> int:
        """Start the development environment."""
        print("🛠️ Starting development environment...")

        cmd = ["docker", "compose", "-f", DOCKER_COMPOSE_DEV_FILE, "up"]
        if build:
            cmd.append("--build")
        if detach:
            cmd.append("--detach")

        return self.runner.run_command(cmd)

    def down(self, volumes: bool = False) -> int:
        """Stop the development environment."""
        print("🛑 Stopping development environment...")

        cmd = ["docker", "compose", "-f", DOCKER_COMPOSE_DEV_FILE, "down"]
        if volumes:
            cmd.append("--volumes")

        return self.runner.run_command(cmd)

    def logs(self, follow: bool = False, service: Optional[str] = None) -> int:
        """Show logs from the development environment."""
        print("📋 Showing development environment logs...")

        cmd = ["docker", "compose", "-f", DOCKER_COMPOSE_DEV_FILE, "logs"]
        if follow:
            cmd.append("--follow")
        if service:
            cmd.append(service)

        return self.runner.run_command(cmd)

    def restart(self, service: Optional[str] = None) -> int:
        """Restart the development environment."""
        print("🔄 Restarting development environment...")

        cmd = ["docker", "compose", "-f", DOCKER_COMPOSE_DEV_FILE, "restart"]
        if service:
            cmd.append(service)

        return self.runner.run_command(cmd)


class TestCommands:
    """Test-related commands."""

    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def run_tests(
        self,
        verbose: bool = False,
        tb: Optional[str] = None,
        markers: Optional[str] = None,
        keywords: Optional[str] = None,
        path: Optional[str] = None,
    ) -> int:
        """Run tests with specified options."""
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
        if path:
            cmd.append(path)

        return self.runner.run_command(cmd)


class QualityCommands:
    """Code quality and linting commands."""

    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def lint(self) -> int:
        """Run all linting checks."""
        print("🔍 Running linting checks...")

        checks = [
            ("📝 Checking code formatting with black...", ["black", "--check", "."]),
            (
                "🔤 Checking import ordering with isort...",
                ["isort", "--check-only", "."],
            ),
            (
                "🏷️ Checking title case...",
                ["python3", "scripts/dev/title_case_check.py", "--check-only"],
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


class SeedCommands:
    """Database seeding commands."""

    SERVICE_NAME = "bedlam-connect-dev"

    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def _is_dev_container_running(self) -> bool:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                DOCKER_COMPOSE_DEV_FILE,
                "ps",
                "-q",
                self.SERVICE_NAME,
            ],
            capture_output=True,
            text=True,
            cwd=self.runner.project_root,
        )
        return bool(result.stdout.strip())

    def _wrap_for_compose(self, container_cmd: List[str]) -> List[str]:
        if self._is_dev_container_running():
            return [
                "docker",
                "compose",
                "-f",
                DOCKER_COMPOSE_DEV_FILE,
                "exec",
                self.SERVICE_NAME,
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
            self.SERVICE_NAME,
            *container_cmd,
        ]

    def seed(self) -> int:
        """Seed the dev database with fixture users."""
        # `dev seed` runs in a one-off `docker compose run --no-deps` container
        # that bypasses start-dev.sh, so migrations must be applied explicitly
        # here — otherwise a freshly added revision crashes seed against a
        # stale schema with a raw OperationalError.
        print("🧱 Applying migrations before seeding...")
        migrate_cmd = self._wrap_for_compose(
            ["alembic", "-c", "config/alembic.ini", "upgrade", "head"]
        )
        rc = self.runner.run_command(migrate_cmd)
        if rc != 0:
            print("❌ Migrations failed — aborting seed.")
            return rc

        print("🌱 Seeding fixture users...")
        seed_cmd = self._wrap_for_compose(["python", "scripts/dev/seed.py"])
        return self.runner.run_command(seed_cmd)


class RoutesCommands:
    """Route inspection commands."""

    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def list_routes(self, prefix: Optional[str] = None) -> int:
        """Print every HTTP route registered on `src.main:app`.

        Useful for spotting router shadowing — when two `include_router`
        calls register handlers for the same path and the second one is
        silently ignored. Without this, the only way to discover a conflict
        is by failing tests at runtime.

        Output groups routes by their path prefix (first segment) and prints
        each as `METHOD /path  →  module.handler`.
        """
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


class SetupCommands:
    """Environment setup commands."""

    def __init__(self, runner: CLIRunner):
        self.runner = runner

    def setup(self) -> int:
        """Set up the development environment."""
        print("🔧 Setting up development environment...")

        # Check Docker installation
        if not self.runner.check_docker_installation():
            return 1

        # Check compose file
        dev_compose_file = self.runner.project_root / DOCKER_COMPOSE_DEV_FILE
        if not dev_compose_file.exists():
            print(f"❌ Development compose file not found: {dev_compose_file}")
            return 1
        print(f"✅ Development compose file found: {dev_compose_file}")

        # Create .env file if it doesn't exist
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
        self.test = TestCommands(self.runner)
        self.quality = QualityCommands(self.runner)
        self.setup = SetupCommands(self.runner)
        self.seed_cmd = SeedCommands(self.runner)
        self.routes_cmd = RoutesCommands(self.runner)

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
        self._add_setup_parser(subparsers)
        self._add_seed_parser(subparsers)
        self._add_routes_parser(subparsers)

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
        parser = subparsers.add_parser("test", help="Run tests")
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
        parser.add_argument("path", nargs="?", help="Test path or file")
        parser.set_defaults(
            func=lambda args: self.test.run_tests(
                args.verbose, args.tb, args.markers, args.keywords, args.path
            )
        )

    def _add_lint_parser(self, subparsers):
        parser = subparsers.add_parser("lint", help="Run linting checks")
        parser.set_defaults(func=lambda args: self.quality.lint())

    def _add_setup_parser(self, subparsers):
        parser = subparsers.add_parser("setup", help="Set up development environment")
        parser.set_defaults(func=lambda args: self.setup.setup())

    def _add_seed_parser(self, subparsers):
        parser = subparsers.add_parser(
            "seed", help="Seed the dev database with fixture users"
        )
        parser.set_defaults(func=lambda args: self.seed_cmd.seed())

    def _add_routes_parser(self, subparsers):
        parser = subparsers.add_parser(
            "routes",
            help="List every HTTP route registered on the app (catches shadowing)",
        )
        parser.add_argument(
            "prefix",
            nargs="?",
            help="Filter by path prefix (e.g. /users)",
        )
        parser.set_defaults(func=lambda args: self.routes_cmd.list_routes(args.prefix))

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
