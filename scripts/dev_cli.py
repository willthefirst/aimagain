#!/usr/bin/env python3
"""Development CLI."""

import argparse
import os
import re
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
        # Per-worktree `docker compose` project name (see #748). Each
        # worktree gets its own container stack — containers, volumes,
        # network — so two worktrees can run the dev container in
        # parallel and `dev seed` from a worktree targets the worktree's
        # own volume instead of leaking into the main checkout. The user
        # can still override by exporting COMPOSE_PROJECT_NAME themselves;
        # we only set it when nothing else has.
        self.compose_project_name = self._derive_compose_project_name()

    def _derive_compose_project_name(self) -> str:
        # docker-compose project names must be lowercase alnum + `-`/`_`,
        # so slugify the project-root directory name. `bedlam-` prefix
        # keeps the namespace human-grep-able across docker installs that
        # also host other compose projects.
        raw = self.project_root.name.lower()
        slug = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-") or "bedlam"
        return f"bedlam-{slug}" if not slug.startswith("bedlam") else slug

    def _compose_env(self, extra: Optional[dict] = None) -> dict:
        env = os.environ.copy()
        env.setdefault("COMPOSE_PROJECT_NAME", self.compose_project_name)
        if extra:
            env.update(extra)
        return env

    def _is_compose_cmd(self, cmd: List[str]) -> bool:
        # Recognize `docker compose` and `docker-compose` invocations
        # — those are the only ones that consult COMPOSE_PROJECT_NAME.
        # Everything else (alembic, pytest, gh, git, python, …) runs
        # with the inherited parent env so its behaviour is unchanged.
        if not cmd:
            return False
        if cmd[0] == "docker-compose":
            return True
        return cmd[0] == "docker" and len(cmd) > 1 and cmd[1] == "compose"

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> int:
        if cwd is None:
            cwd = self.project_root

        print(f"🚀 Running: {' '.join(cmd)}")
        print(f"📁 Working directory: {cwd}")

        env = self._compose_env() if self._is_compose_cmd(cmd) else None
        try:
            result = subprocess.run(cmd, cwd=cwd, env=env, check=False)
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
            env=self._compose_env(),
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
        affected: bool = False,
        base: str = "origin/main",
    ) -> int:
        # Inner-loop guard (#648). Default sequence: auto-fmt → lint →
        # pytest. Lint failures stop before pytest so the agent fixes
        # them once instead of running tests then re-running after the
        # lint surprise. `--skip-lint` is the escape hatch for the
        # "I know my code's dirty, I'm debugging a failing test" case.
        if not skip_lint:
            pre_fmt_dirty = self._dirty_files()
            fmt_rc = self.quality.fmt()
            if fmt_rc != 0:
                print(
                    "❌ Formatter failed before tests could run. Fix the "
                    "underlying issue or re-run with `dev test --skip-lint` "
                    "to bypass the pre-step."
                )
                return fmt_rc
            self._warn_on_fmt_mutations(pre_fmt_dirty)
            lint_rc = self.quality.lint()
            if lint_rc != 0:
                print(
                    "❌ Lint failed before tests could run. Fix the "
                    "violations above or re-run with `dev test --skip-lint` "
                    "to bypass the pre-step."
                )
                return lint_rc

        # `--affected` resolves changed-files-vs-base into a pytest path
        # list using the colocated-test convention. Falls back to the
        # full suite on blast-radius hits and exits 0 without invoking
        # pytest when nothing test-relevant changed (e.g. README-only
        # PRs). See `scripts/affected_tests.py` for the contract.
        affected_paths: Optional[List[str]] = None
        if affected:
            if paths:
                print("❌ `--affected` is mutually exclusive with explicit paths.")
                return 2
            from scripts.affected_tests import (
                changed_files,
                select_affected_tests,
            )

            files = changed_files(base, self.runner.project_root)
            selection = select_affected_tests(files, self.runner.project_root)
            print(f"📍 Affected selector: {selection.reason}")
            if not selection.full_suite and not selection.paths:
                print("✅ No affected tests; skipping pytest.")
                return 0
            affected_paths = selection.pytest_args()

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
        if affected_paths is not None:
            cmd.extend(affected_paths)
        elif paths:
            cmd.extend(self.PATH_ALIASES.get(p, p) for p in paths)

        return self.runner.run_command(cmd)

    def _dirty_files(self) -> set:
        # Snapshot `git status --porcelain` as a set of paths. Used by the
        # fmt-mutation surfacing below: if a file is dirty AFTER fmt but
        # was clean BEFORE, fmt rewrote it — and if the agent has an
        # in-flight Edit on that file, the next Edit will fail with a
        # generic "modified since read" error. We surface what fmt
        # actually touched so the cause is obvious. See #745.
        try:
            out = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
                cwd=self.runner.project_root,
            )
        except FileNotFoundError:
            return set()
        return {line[3:] for line in out.stdout.splitlines() if line[3:]}

    def _warn_on_fmt_mutations(self, pre_fmt_dirty: set) -> None:
        post_fmt_dirty = self._dirty_files()
        newly_dirty = sorted(post_fmt_dirty - pre_fmt_dirty)
        if not newly_dirty:
            return
        print("")
        print(
            f"⚠  `dev fmt` rewrote {len(newly_dirty)} file(s) "
            f"while preparing to run tests:"
        )
        for path in newly_dirty:
            print(f"     {path}")
        print(
            "   If you have in-flight edits to these files, re-read them "
            "before editing further."
        )
        print("   Pass --skip-lint to bypass the auto-fmt step.")
        print("")


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
                "🧩 Checking template formatting with djlint...",
                [
                    "djlint",
                    "src/framework/templates",
                    "src/domain/templates",
                    "--check",
                ],
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
            (
                "🤝 Checking contract-form coverage...",
                [sys.executable, "scripts/dev/contract_form_coverage_check.py"],
            ),
            (
                "🌱 Checking seed generator coverage...",
                [sys.executable, "-m", "scripts.dev.seed.lint_coverage"],
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

        # djlint is non-idempotent on `{% block %}/{% endblock %}` indent —
        # the first pass leaves `{% endblock %}` at column 0; a second pass
        # bumps it to column 2 (or vice versa). Running it twice converges
        # in practice. Without this, `dev lint`'s `djlint --check` flags
        # drift on the very output `dev fmt` just produced.
        djlint_cmd = [
            "djlint",
            "src/framework/templates",
            "src/domain/templates",
            "--reformat",
        ]
        steps = [
            ("📝 Formatting code with black...", ["black", "."]),
            (
                "🔤 Sorting imports with isort...",
                ["isort", "src", "tests", "scripts", "alembic", "conftest.py"],
            ),
            ("🧩 Formatting templates with djlint (pass 1/2)...", djlint_cmd),
            ("🧩 Formatting templates with djlint (pass 2/2)...", djlint_cmd),
        ]

        exit_code = 0
        for description, cmd in steps:
            print(description)
            result = self.runner.run_command(cmd)
            # `djlint --reformat` exits 1 when it rewrites files — same
            # signal as `git diff --exit-code`. Black and isort instead
            # exit 0 in that case, so treating any non-zero as failure
            # would make every template-touching `dev fmt` run report
            # failure. Special-case djlint so the step is success-on-fix.
            if cmd[0] == "djlint" and "--reformat" in cmd and result == 1:
                result = 0
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

    @staticmethod
    def _in_container() -> bool:
        """True when already running inside a Docker container."""
        import os

        return os.path.exists("/.dockerenv")

    def seed(self) -> int:
        # `dev seed` runs in a one-off `docker compose run --no-deps` container
        # that bypasses start-dev.sh, so migrations must be applied explicitly
        # here — otherwise a freshly added revision crashes seed against a
        # stale schema with a raw OperationalError.
        #
        # When invoked from *inside* a container (e.g. on the prod droplet via
        # `docker exec … dev seed`), docker is not available so we skip the
        # compose wrapper and run alembic + the seed script directly.
        from scripts.dev.migrate import run_alembic

        in_container = self._in_container()

        print("🧱 Applying migrations before seeding...")
        rc = run_alembic(
            self.runner,
            ["upgrade", "head"],
            mode="host" if in_container else "compose",
            service_name=self.SERVICE_NAME,
        )
        if rc != 0:
            print("❌ Migrations failed — aborting seed.")
            return rc

        print("🌱 Seeding fixture users...")
        seed_cmd = ["python", "-m", "scripts.dev.seed"]
        if not in_container:
            seed_cmd = self.runner.wrap_for_compose(self.SERVICE_NAME, seed_cmd)
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


class WorktreeCommands:
    """`dev worktree {add,list,gc}` — issue-named worktrees plus GC of
    merged ones.

    Background: multi-agent sessions share `/home/user/bedlam-connect`,
    so the project's convention is one git worktree per task under
    `.claude/worktrees/`. The harness's `EnterWorktree` tool used to
    name them by agent UUID, which made `ls .claude/worktrees/` unreadable
    and let stale worktrees accumulate after their branch merged. See
    #744 for the friction this addresses."""

    WORKTREES_DIR = ".claude/worktrees"

    def __init__(self, runner: CLIRunner) -> None:
        self.runner = runner

    def _slugify(self, text: str) -> str:
        # ASCII slug: lowercase, hyphen-separated, no leading/trailing dashes.
        # Limited to alnum + hyphen so it's always a valid directory and
        # branch name.
        out = []
        prev_dash = False
        for ch in text.lower():
            if ch.isalnum():
                out.append(ch)
                prev_dash = False
            elif not prev_dash:
                out.append("-")
                prev_dash = True
        return "".join(out).strip("-")

    def _worktrees_root(self) -> Path:
        return self.runner.project_root / self.WORKTREES_DIR

    def _run_git(self, args: List[str]) -> "subprocess.CompletedProcess":
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.runner.project_root,
        )

    def add(self, name: str, base: str = "origin/main") -> int:
        # Refuse to create a worktree whose name looks like an opaque UUID
        # — the whole point is human-readable, issue-shaped names.
        if self._looks_like_uuid(name):
            print(
                f"❌ Refusing to create worktree with opaque name '{name}'. "
                "Use an issue-shaped name like `issue-707-verification-badge` "
                "or `707` (which expands to `issue-707`)."
            )
            return 2

        slug = self._slugify(name)
        if slug.isdigit():
            slug = f"issue-{slug}"
        path = self._worktrees_root() / slug
        if path.exists():
            print(f"❌ Worktree path already exists: {path}")
            return 1

        branch = f"fix/{slug}" if not slug.startswith("issue-") else f"fix/{slug[6:]}"
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"📂 Creating worktree at {path} on branch {branch} (base: {base})")
        result = self._run_git(["worktree", "add", str(path), "-b", branch, base])
        if result.returncode != 0:
            print(result.stderr.rstrip())
            return result.returncode
        print(f"✅ Worktree ready: {path}")
        print(f"   Branch: {branch}")
        return 0

    def _looks_like_uuid(self, name: str) -> bool:
        # Heuristic: 6+ consecutive hex chars and no human-meaningful
        # words. Catches `a3f9c2`-style agent IDs without rejecting
        # `issue-707-...`. Worktrees that already include `issue-` or any
        # alpha-rich slug are fine.
        if "issue-" in name or "fix-" in name:
            return False
        hex_chars = sum(1 for c in name if c in "0123456789abcdefABCDEF")
        return hex_chars >= 6 and hex_chars / max(len(name), 1) > 0.6

    def list_(self) -> int:
        result = self._run_git(["worktree", "list", "--porcelain"])
        if result.returncode != 0:
            print(result.stderr.rstrip())
            return result.returncode
        print(result.stdout.rstrip())
        return 0

    def gc(self, assume_yes: bool = False) -> int:
        # Remove worktrees whose branches are fully merged into
        # origin/main (or whose branches no longer exist).
        # `git branch --merged` prefixes the current branch with `*` and
        # worktree-checked-out branches with `+`. Strip both, then drop
        # any entry that points at a remote ref (`origin/main` etc.) so
        # GC only ever considers local branches we created.
        merged_branches: set = set()
        for raw in self._run_git(
            ["branch", "--merged", "origin/main"]
        ).stdout.splitlines():
            cleaned = raw.strip().lstrip("*+").strip()
            if (
                not cleaned
                or "/" in cleaned.split()[0]
                and cleaned.startswith("origin/")
            ):
                continue
            merged_branches.add(cleaned)

        candidates: List[tuple] = []
        for entry in self._parse_worktree_list():
            path = entry.get("worktree")
            branch = entry.get("branch", "")
            if path is None:
                continue
            # Refuse to GC the main checkout no matter what.
            if Path(path).resolve() == self.runner.project_root.resolve():
                continue
            if self.WORKTREES_DIR not in path:
                continue
            short = branch.removeprefix("refs/heads/")
            if short in merged_branches or not short:
                candidates.append((path, short))

        if not candidates:
            print("✅ No merged worktrees to remove.")
            return 0

        print("The following worktrees will be removed (their branches are merged):")
        for path, branch in candidates:
            print(f"  {path}  ({branch or '<no branch>'})")

        if not assume_yes:
            print("Pass --yes to confirm.")
            return 0

        for path, branch in candidates:
            print(f"🧹 Removing {path}")
            rm = self._run_git(["worktree", "remove", "--force", path])
            if rm.returncode != 0:
                print(rm.stderr.rstrip())
                continue
            if branch:
                self._run_git(["branch", "-D", branch])
        print("✅ GC complete.")
        return 0

    def _parse_worktree_list(self) -> List[dict]:
        result = self._run_git(["worktree", "list", "--porcelain"])
        entries: List[dict] = []
        current: dict = {}
        for raw in result.stdout.splitlines():
            if not raw.strip():
                if current:
                    entries.append(current)
                    current = {}
                continue
            key, _, value = raw.partition(" ")
            current[key] = value
        if current:
            entries.append(current)
        return entries


class PushCommands:
    """`dev push` — `git push -u` with a pre-flight duplicate-PR check.

    Multi-agent retros (#746) reported the same loss-of-30-minutes pattern:
    claim an issue, build the fix, open a PR, then discover at rebase time
    that another agent had already merged the same fix. The label-based
    claim primitive doesn't gate work-in-progress between agents.

    This wrapper parses the current branch for an issue number and, if
    found, asks GitHub whether a PR for that issue already exists or
    whether a merge commit mentioning it is already on origin/main.
    The user is prompted before push so a real overlap can be reviewed
    and cancelled, but `--yes` (or `--force`) bypasses the prompt for
    the no-issue-number case.
    """

    # Branch-name patterns that carry an issue number. The capture group
    # is the issue number itself. Order matters — most-specific first.
    _BRANCH_PATTERNS = [
        re.compile(r"(?:^|/)fix[-/](\d+)(?:[-/]|$)"),
        re.compile(r"(?:^|/)issue[-/](\d+)(?:[-/]|$)"),
        re.compile(r"(?:^|/)claude/[^/]*-(\d+)-"),
    ]

    def __init__(self, runner: CLIRunner) -> None:
        self.runner = runner

    def _current_branch(self) -> Optional[str]:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.runner.project_root,
        )
        return result.stdout.strip() or None

    def _issue_number_from_branch(self, branch: str) -> Optional[int]:
        for pat in self._BRANCH_PATTERNS:
            m = pat.search(branch)
            if m:
                return int(m.group(1))
        return None

    def _gh_existing_prs(self, issue: int) -> List[dict]:
        # Best-effort: if `gh` isn't installed or the call fails, return
        # [] so push isn't blocked by tooling absence.
        result = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--search",
                f"#{issue} in:title,body",
                "--state",
                "all",
                "--json",
                "number,state,title,url",
                "--limit",
                "10",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.runner.project_root,
        )
        if result.returncode != 0:
            return []
        try:
            import json

            data = json.loads(result.stdout or "[]")
        except (ValueError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _grep_main_log(self, issue: int) -> List[str]:
        result = subprocess.run(
            [
                "git",
                "log",
                "--grep",
                f"#{issue}",
                "origin/main",
                "--oneline",
                "-5",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.runner.project_root,
        )
        if result.returncode != 0:
            return []
        return [ln for ln in result.stdout.splitlines() if ln.strip()]

    def push(
        self,
        force: bool = False,
        yes: bool = False,
        extra_args: Optional[List[str]] = None,
    ) -> int:
        branch = self._current_branch()
        if not branch:
            print("❌ Could not resolve current branch.")
            return 1

        issue = self._issue_number_from_branch(branch)
        if issue is not None and not yes:
            overlaps = self._collect_overlaps(issue)
            if overlaps and not self._confirm_push(branch, issue, overlaps):
                return 2

        cmd = ["git", "push", "-u", "origin", branch]
        if force:
            cmd.append("--force-with-lease")
        if extra_args:
            cmd.extend(extra_args)
        return self.runner.run_command(cmd)

    def _collect_overlaps(self, issue: int) -> dict:
        return {
            "prs": self._gh_existing_prs(issue),
            "commits": self._grep_main_log(issue),
        }

    def _confirm_push(self, branch: str, issue: int, overlaps: dict) -> bool:
        prs = overlaps.get("prs") or []
        commits = overlaps.get("commits") or []
        if not prs and not commits:
            return True
        print(f"⚠  Issue #{issue} may already be addressed elsewhere:")
        for pr in prs:
            number = pr.get("number")
            state = (pr.get("state") or "?").upper()
            title = pr.get("title", "")
            print(f"    PR #{number} ({state}): {title}")
        for line in commits:
            print(f"    commit on main: {line}")
        print(
            "Push anyway? Re-run with --yes to skip this prompt, or "
            "Ctrl-C / answer 'n' to abort."
        )
        try:
            answer = input(f"Push branch '{branch}'? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"
        return answer in {"y", "yes"}


class MergeCommands:
    """`dev merge [<pr-number>]` — watch a PR until Mergify lands it.

    Mergify queues PRs automatically when they open (see .mergify.yml),
    waits for CI to go green, runs speculative CI on the rebased batch,
    and squash-merges. This command watches and reports that process,
    exiting non-zero if a check fails. See scripts/README.md#merging-prs.
    """

    POLL_SECONDS = 30
    DEFAULT_TIMEOUT_SECONDS = 30 * 60

    def __init__(self, runner: CLIRunner) -> None:
        self.runner = runner

    def _resolve_pr_number(self, explicit: Optional[int]) -> Optional[int]:
        if explicit is not None:
            return explicit
        result = subprocess.run(
            ["gh", "pr", "view", "--json", "number"],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.runner.project_root,
        )
        if result.returncode != 0:
            return None
        try:
            import json

            data = json.loads(result.stdout or "{}")
            number = data.get("number")
            return int(number) if number is not None else None
        except (ValueError, KeyError):
            return None

    def _pr_status(self, pr: int) -> dict:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--json",
                "mergeStateStatus,mergeable,statusCheckRollup,state",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.runner.project_root,
        )
        if result.returncode != 0:
            return {}
        try:
            import json

            return json.loads(result.stdout or "{}")
        except ValueError:
            return {}

    def _checks_failing(self, status: dict) -> List[str]:
        rollup = status.get("statusCheckRollup") or []
        failed: List[str] = []
        for check in rollup:
            conclusion = (check.get("conclusion") or "").upper()
            if conclusion in {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}:
                name = check.get("name") or check.get("context") or "<unknown>"
                failed.append(name)
        return failed

    def merge(
        self,
        pr: Optional[int] = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> int:
        import time

        number = self._resolve_pr_number(pr)
        if number is None:
            print(
                "❌ Could not determine PR number — pass one explicitly "
                "(`dev merge 123`) or run from a branch with an open PR."
            )
            return 1

        print(f"⏳ Watching PR #{number} — Mergify will queue it when CI is green.")
        deadline = time.monotonic() + timeout_seconds
        last_state: Optional[str] = None
        while time.monotonic() < deadline:
            status = self._pr_status(number)
            if not status:
                print("⚠ Could not fetch PR status — retrying.")
                time.sleep(self.POLL_SECONDS)
                continue
            if (status.get("state") or "").upper() == "MERGED":
                print(f"✅ PR #{number} is merged.")
                return 0
            failing = self._checks_failing(status)
            if failing:
                print(f"❌ PR #{number} has failing checks: {', '.join(failing)}")
                return 3
            state = (status.get("mergeStateStatus") or "").upper()
            if state != last_state:
                print(f"  state: {state}")
                last_state = state
            time.sleep(self.POLL_SECONDS)
        print(f"⏰ Timed out after {timeout_seconds}s waiting on PR #{number}.")
        return 4


class ClaimCommands:
    """`dev claim <issue>` / `dev unclaimed-issues` / `dev claimed-issues`
    — assignee-based atomic claiming.

    The `in-progress` label is read-modify-write with no compare. Two
    agents reading the issue list at the same time both see no label,
    both add it, both proceed — duplicate work. GitHub assignees are
    atomic at the API level: `gh issue edit --add-assignee` either wins
    or the user is already assigned. This subcommand uses that
    primitive and surfaces lost races as a non-zero exit code so the
    agent's automation can pick a different issue. See #742 / #750.

    Exit codes:
      0 — won the claim (issue is now assigned to the user).
      1 — already claimed by someone else.
      2 — network or other failure.
    """

    def __init__(self, runner: CLIRunner) -> None:
        self.runner = runner

    def _gh_json(self, args: List[str]) -> Optional[dict]:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.runner.project_root,
        )
        if result.returncode != 0:
            return None
        try:
            import json

            return json.loads(result.stdout or "{}")
        except ValueError:
            return None

    def _current_user(self) -> Optional[str]:
        data = self._gh_json(["api", "user", "--jq", "{login}"])
        if not data:
            return None
        return data.get("login")

    def claim(self, issue: int, assignee: Optional[str] = None) -> int:
        who = assignee or self._current_user()
        if not who:
            print(
                "❌ Could not resolve a GitHub user to claim with. "
                "Pass --assignee <user> or run `gh auth login`."
            )
            return 2

        existing = self._gh_json(
            ["issue", "view", str(issue), "--json", "assignees,state,title,url"]
        )
        if not existing:
            print(f"❌ Could not fetch issue #{issue}.")
            return 2
        if (existing.get("state") or "").lower() != "open":
            print(f"❌ Issue #{issue} is not open (state: {existing.get('state')}).")
            return 2

        prior = [a.get("login") for a in (existing.get("assignees") or [])]
        if prior and who not in prior:
            print(f"❌ Issue #{issue} is already claimed by: {', '.join(prior)}")
            print(f"    Title: {existing.get('title', '')}")
            return 1

        # Attempt the claim. `gh issue edit --add-assignee` is atomic
        # — if a second agent had assigned themselves between our view
        # and our edit, the edit still succeeds (assignee is additive)
        # so we re-read and confirm we won the race.
        rc = self.runner.run_command(
            ["gh", "issue", "edit", str(issue), "--add-assignee", who]
        )
        if rc != 0:
            return 2

        post = self._gh_json(["issue", "view", str(issue), "--json", "assignees"])
        post_assignees = [a.get("login") for a in (post or {}).get("assignees") or []]
        if who not in post_assignees:
            print(f"❌ Claim of #{issue} did not stick — assignment was reverted.")
            return 2
        if post_assignees and post_assignees != [who]:
            # Someone else also assigned themselves. Decide by lexical
            # order to give both agents a deterministic loser without
            # extra round-trips.
            winner = sorted(post_assignees)[0]
            if winner != who:
                print(
                    f"❌ Lost race on #{issue} — co-assignees: "
                    f"{', '.join(sorted(post_assignees))}. Winner by "
                    f"deterministic tiebreak: {winner}. Unassigning."
                )
                self.runner.run_command(
                    ["gh", "issue", "edit", str(issue), "--remove-assignee", who]
                )
                return 1

        print(f"✅ Claimed issue #{issue} for @{who}.")
        return 0

    def list_unclaimed(self, limit: int = 30) -> int:
        return self.runner.run_command(
            [
                "gh",
                "issue",
                "list",
                "--search",
                "no:assignee state:open",
                "--limit",
                str(limit),
            ]
        )

    def list_claimed(self, assignee: Optional[str] = None, limit: int = 30) -> int:
        who = assignee or self._current_user()
        if not who:
            print(
                "❌ Could not resolve a user. Pass --assignee <user> or "
                "run `gh auth login`."
            )
            return 2
        return self.runner.run_command(
            [
                "gh",
                "issue",
                "list",
                "--search",
                f"assignee:{who} state:open",
                "--limit",
                str(limit),
            ]
        )


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
        self.worktree_cmd = WorktreeCommands(self.runner)
        self.push_cmd = PushCommands(self.runner)
        self.merge_cmd = MergeCommands(self.runner)
        self.claim_cmd = ClaimCommands(self.runner)

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
        self._add_worktree_parser(subparsers)
        self._add_push_parser(subparsers)
        self._add_merge_parser(subparsers)
        self._add_claim_parser(subparsers)

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
            "--affected",
            action="store_true",
            help=(
                "Run only test files relevant to files changed in this "
                "branch vs --base. Mutually exclusive with explicit paths. "
                "Falls back to the full suite when a blast-radius file "
                "(pyproject.toml, alembic/, src/framework/config.py, ...) "
                "changed. See `scripts/affected_tests.py`."
            ),
        )
        parser.add_argument(
            "--base",
            default="origin/main",
            help="Base ref for --affected diff (default: origin/main).",
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
                args.affected,
                args.base,
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

    def _add_worktree_parser(self, subparsers):
        parser = subparsers.add_parser(
            "worktree",
            help="Manage per-task git worktrees under .claude/worktrees/",
            description=(
                "Multi-agent sessions share one working tree; the project's "
                "convention is one git worktree per task. `dev worktree add "
                "<N>` creates `.claude/worktrees/issue-<N>-<slug>` off a "
                "fresh origin/main and refuses opaque UUID names. `dev "
                "worktree gc` removes worktrees whose branches are merged. "
                "See #744."
            ),
        )
        sub = parser.add_subparsers(dest="worktree_command")

        add = sub.add_parser("add", help="Create a worktree for an issue")
        add.add_argument(
            "name",
            help=(
                "Issue number (e.g. 707) or descriptive name "
                "(e.g. issue-707-verification-badge)"
            ),
        )
        add.add_argument(
            "--base",
            default="origin/main",
            help="Base ref for the new branch (default: origin/main)",
        )
        add.set_defaults(func=lambda args: self.worktree_cmd.add(args.name, args.base))

        ls = sub.add_parser("list", help="List all worktrees")
        ls.set_defaults(func=lambda args: self.worktree_cmd.list_())

        gc = sub.add_parser(
            "gc",
            help="Remove worktrees whose branches are merged into origin/main",
        )
        gc.add_argument(
            "--yes",
            action="store_true",
            help="Confirm removal (without this, gc only previews)",
        )
        gc.set_defaults(func=lambda args: self.worktree_cmd.gc(args.yes))

        def _print_help(_args):
            parser.print_help()
            return 1

        parser.set_defaults(func=_print_help)

    def _add_push_parser(self, subparsers):
        parser = subparsers.add_parser(
            "push",
            help="`git push -u` with a pre-flight duplicate-PR check",
            description=(
                "Wraps `git push -u origin <current-branch>`. If the branch "
                "name carries an issue number (e.g. `fix/697-foo`, "
                "`claude/fix-697-foo`), first checks whether a PR for that "
                "issue already exists and whether origin/main already has a "
                "merge commit mentioning it. If so, prompts before pushing. "
                "Use --yes to skip the prompt non-interactively. See #746."
            ),
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip the duplicate-PR prompt and push regardless.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Forward --force-with-lease to git push.",
        )
        parser.set_defaults(func=lambda args: self.push_cmd.push(args.force, args.yes))

    def _add_merge_parser(self, subparsers):
        parser = subparsers.add_parser(
            "merge",
            help="Watch a PR until Mergify queues and lands it",
            description=(
                "Polls the PR until Mergify squash-merges it or a check fails. "
                "Mergify auto-queues PRs whose CI is green (see .mergify.yml); "
                "this command just watches and reports. See "
                "scripts/README.md#merging-prs."
            ),
        )
        parser.add_argument(
            "pr",
            type=int,
            nargs="?",
            help="PR number. Defaults to the PR for the current branch.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=MergeCommands.DEFAULT_TIMEOUT_SECONDS,
            help=(
                "Give up after this many seconds (default: "
                f"{MergeCommands.DEFAULT_TIMEOUT_SECONDS})."
            ),
        )
        parser.set_defaults(
            func=lambda args: self.merge_cmd.merge(args.pr, args.timeout)
        )

    def _add_claim_parser(self, subparsers):
        claim = subparsers.add_parser(
            "claim",
            help="Atomically claim an issue via GitHub assignee",
            description=(
                "Assigns the issue to the current user (or --assignee) using "
                "`gh issue edit --add-assignee`. Exits 0 on a successful "
                "claim, 1 if already claimed by someone else, 2 on error. "
                "Use as a precondition before opening a PR to avoid the "
                "label-claim race (#742 / #750)."
            ),
        )
        claim.add_argument("issue", type=int, help="Issue number to claim")
        claim.add_argument(
            "--assignee",
            help="GitHub login to claim as (defaults to authenticated user)",
        )
        claim.set_defaults(
            func=lambda args: self.claim_cmd.claim(args.issue, args.assignee)
        )

        unclaimed = subparsers.add_parser(
            "unclaimed-issues",
            help="List open issues with no assignee",
        )
        unclaimed.add_argument("--limit", type=int, default=30)
        unclaimed.set_defaults(
            func=lambda args: self.claim_cmd.list_unclaimed(args.limit)
        )

        claimed = subparsers.add_parser(
            "claimed-issues",
            help="List open issues assigned to me (or --assignee)",
        )
        claimed.add_argument("--assignee")
        claimed.add_argument("--limit", type=int, default=30)
        claimed.set_defaults(
            func=lambda args: self.claim_cmd.list_claimed(args.assignee, args.limit)
        )

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
