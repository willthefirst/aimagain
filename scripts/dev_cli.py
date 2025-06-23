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

    if args.markers:
        cmd.extend(["-m", args.markers])

    if args.path:
        cmd.append(args.path)

    return run_command(cmd)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Development CLI for the aimagain app",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s dev up --build    # Start development environment with rebuild
  %(prog)s dev down          # Stop development environment
  %(prog)s dev logs -f       # Follow development logs
  %(prog)s test -m api       # Run API tests only
  %(prog)s test tests/       # Run specific test directory
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
    test_parser.add_argument("-m", "--markers", help="Run tests with specific markers")
    test_parser.add_argument("path", nargs="?", help="Test path or file")
    test_parser.set_defaults(func=cmd_test)

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
