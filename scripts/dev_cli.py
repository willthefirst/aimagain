#!/usr/bin/env python3
"""
Development CLI for the aimagain app.

This CLI provides convenient commands for common development tasks.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def run_command(cmd: list[str], cwd: Path = None) -> int:
    """Run a command and return its exit code."""
    if cwd is None:
        cwd = get_project_root()

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


def cmd_dev_up(args):
    """Start the development environment."""
    print("🛠️ Starting development environment...")

    cmd = ["docker", "compose", "-f", "docker-compose.dev.yml", "up"]

    if args.build:
        cmd.append("--build")

    if args.detach:
        cmd.append("--detach")

    return run_command(cmd)


def cmd_dev_down(args):
    """Stop the development environment."""
    print("🛑 Stopping development environment...")

    cmd = ["docker", "compose", "-f", "docker-compose.dev.yml", "down"]

    if args.volumes:
        cmd.append("--volumes")

    return run_command(cmd)


def cmd_dev_logs(args):
    """Show logs from the development environment."""
    print("📋 Showing development environment logs...")

    cmd = ["docker", "compose", "-f", "docker-compose.dev.yml", "logs"]

    if args.follow:
        cmd.append("--follow")

    if args.service:
        cmd.append(args.service)

    return run_command(cmd)


def cmd_dev_restart(args):
    """Restart the development environment."""
    print("🔄 Restarting development environment...")

    cmd = ["docker", "compose", "-f", "docker-compose.dev.yml", "restart"]

    if args.service:
        cmd.append(args.service)

    return run_command(cmd)


def cmd_test(args):
    """Run tests."""
    print("🧪 Running tests...")

    cmd = ["pytest"]

    if args.verbose:
        cmd.append("-v")

    if args.tb:
        cmd.extend(["--tb", args.tb])

    if args.markers:
        cmd.extend(["-m", args.markers])

    if args.keywords:
        cmd.extend(["-k", args.keywords])

    if args.path:
        cmd.append(args.path)

    return run_command(cmd)


def cmd_lint(args):
    """Run code linting and formatting checks."""
    print("🔍 Running linting checks...")

    exit_code = 0

    # Run black check
    print("📝 Checking code formatting with black...")
    result = run_command(["black", "--check", "."])
    if result != 0:
        exit_code = result

    # Run isort check
    print("🔤 Checking import ordering with isort...")
    result = run_command(["isort", "--check-only", "."])
    if result != 0:
        exit_code = result

    # Run title case check
    print("🏷️ Checking title case...")
    result = run_command(["python", "scripts/dev/title_case_check.py", "--check-only"])
    if result != 0:
        exit_code = result

    if exit_code == 0:
        print("✅ All linting checks passed!")
    else:
        print("❌ Some linting checks failed!")

    return exit_code


def cmd_db_setup(args):
    """Set up the database for testing or development."""
    print("🗄️ Setting up database...")

    return run_command(["alembic", "-c", "config/alembic.ini", "upgrade", "head"])


def cmd_ci(args):
    """Run CI checks locally."""
    print("🚀 Running CI checks locally...")

    exit_code = 0

    # Run database setup
    print("\n🗄️ Setting up database...")
    result = run_command(["alembic", "-c", "config/alembic.ini", "upgrade", "head"])
    if result != 0:
        exit_code = result

    # Run tests
    print("\n🧪 Running tests...")
    test_cmd = ["pytest", "-v", "--tb=short"]
    result = run_command(test_cmd)
    if result != 0:
        exit_code = result

    # Run linting
    print("\n🔍 Running linting checks...")
    result = cmd_lint(args)
    if result != 0:
        exit_code = result

    if exit_code == 0:
        print("\n✅ All CI checks passed!")
    else:
        print("\n❌ Some CI checks failed!")

    return exit_code


def cmd_setup(args):
    """Set up the development environment."""
    print("🔧 Setting up development environment...")

    project_root = get_project_root()

    # Check if Docker is installed
    try:
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ Docker is not installed or not accessible")
            print(
                "Please install Docker Desktop: https://www.docker.com/products/docker-desktop"
            )
            return 1
        else:
            print(f"✅ Docker found: {result.stdout.strip()}")
    except FileNotFoundError:
        print("❌ Docker is not installed or not accessible")
        print(
            "Please install Docker Desktop: https://www.docker.com/products/docker-desktop"
        )
        return 1

    # Check if Docker Compose is available
    try:
        result = subprocess.run(
            ["docker", "compose", "version"], capture_output=True, text=True
        )
        if result.returncode != 0:
            print("❌ Docker Compose is not available")
            return 1
        else:
            print(f"✅ Docker Compose found: {result.stdout.strip()}")
    except FileNotFoundError:
        print("❌ Docker Compose is not available")
        return 1

    # Check if docker-compose.dev.yml exists
    dev_compose_file = project_root / "docker-compose.dev.yml"
    if not dev_compose_file.exists():
        print(f"❌ Development compose file not found: {dev_compose_file}")
        return 1
    else:
        print(f"✅ Development compose file found: {dev_compose_file}")

    # Check if .env file exists, create a template if it doesn't
    env_file = project_root / ".env"
    if not env_file.exists():
        print("📝 Creating .env template...")
        env_template = """# Development environment variables
# Copy this file to .env and customize as needed

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/app.db

# Application
DEBUG=true
SECRET_KEY=dev-secret-key-change-in-production

# Development
DEVELOPMENT=true
"""
        try:
            env_file.write_text(env_template)
            print(f"✅ Created .env template: {env_file}")
            print("   Please review and customize the values as needed")
        except Exception as e:
            print(f"❌ Failed to create .env file: {e}")
            return 1
    else:
        print(f"✅ Environment file found: {env_file}")

    print("\n🎉 Setup complete! You can now run:")
    print("   aim dev up        # Start development environment")
    print("   aim dev logs -f    # Follow logs")
    print("   aim test           # Run tests")

    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Development CLI for the aimagain app",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s setup             # Set up development environment
  %(prog)s dev up --build    # Start development environment with rebuild
  %(prog)s dev down          # Stop development environment
  %(prog)s dev logs -f       # Follow development logs
  %(prog)s test -m api       # Run API tests only
  %(prog)s test --tb short   # Run tests with short traceback
  %(prog)s test tests/       # Run specific test directory
  %(prog)s lint              # Run all linting checks
  %(prog)s db-setup          # Set up database
  %(prog)s ci                # Run all CI checks locally
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Development commands
    dev_parser = subparsers.add_parser("dev", help="Development environment commands")
    dev_subparsers = dev_parser.add_subparsers(
        dest="dev_command", help="Development commands"
    )

    # dev up
    up_parser = dev_subparsers.add_parser("up", help="Start development environment")
    up_parser.add_argument(
        "--build", action="store_true", help="Build images before starting"
    )
    up_parser.add_argument(
        "-d", "--detach", action="store_true", help="Run in detached mode"
    )
    up_parser.set_defaults(func=cmd_dev_up)

    # dev down
    down_parser = dev_subparsers.add_parser("down", help="Stop development environment")
    down_parser.add_argument(
        "--volumes", action="store_true", help="Remove volumes as well"
    )
    down_parser.set_defaults(func=cmd_dev_down)

    # dev logs
    logs_parser = dev_subparsers.add_parser(
        "logs", help="Show development environment logs"
    )
    logs_parser.add_argument(
        "-f", "--follow", action="store_true", help="Follow log output"
    )
    logs_parser.add_argument(
        "service", nargs="?", help="Show logs for specific service"
    )
    logs_parser.set_defaults(func=cmd_dev_logs)

    # dev restart
    restart_parser = dev_subparsers.add_parser(
        "restart", help="Restart development environment"
    )
    restart_parser.add_argument("service", nargs="?", help="Restart specific service")
    restart_parser.set_defaults(func=cmd_dev_restart)

    # Test commands
    test_parser = subparsers.add_parser("test", help="Run tests")
    test_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )
    test_parser.add_argument(
        "--tb",
        choices=["short", "long", "line", "native", "no"],
        help="Traceback print mode",
    )
    test_parser.add_argument("-m", "--markers", help="Run tests with specific markers")
    test_parser.add_argument(
        "-k", "--keywords", help="Run tests matching keyword expressions"
    )
    test_parser.add_argument("path", nargs="?", help="Test path or file")
    test_parser.set_defaults(func=cmd_test)

    # Lint commands
    lint_parser = subparsers.add_parser("lint", help="Run linting checks")
    lint_parser.set_defaults(func=cmd_lint)

    # Database setup commands
    db_parser = subparsers.add_parser("db-setup", help="Set up database")
    db_parser.set_defaults(func=cmd_db_setup)

    # CI commands
    ci_parser = subparsers.add_parser("ci", help="Run CI checks locally")
    ci_parser.set_defaults(func=cmd_ci)

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Set up development environment")
    setup_parser.set_defaults(func=cmd_setup)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "dev" and not args.dev_command:
        dev_parser.print_help()
        return 1

    # Run the appropriate command
    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
