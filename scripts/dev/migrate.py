"""
Helpers for running alembic against this project.

`run_alembic` centralizes the `alembic -c config/alembic.ini ...` invocation
so call sites don't have to spell out the config path or the host-vs-compose
distinction. The thin `generate / up / down / roundtrip` wrappers below back
the user-facing `dev migrate ...` subcommands; they all run in host mode and
read DATABASE_URL from the environment.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from scripts.dev_cli import CLIRunner

ALEMBIC_CONFIG = "config/alembic.ini"
DEFAULT_SERVICE_NAME = "bedlam-connect-dev"
DEFAULT_ROUNDTRIP_SCRATCH = "/tmp/bedlam-migrate-roundtrip.db"


def run_alembic(
    runner: "CLIRunner",
    args: list[str],
    *,
    mode: Literal["host", "compose"],
    service_name: str = DEFAULT_SERVICE_NAME,
) -> int:
    """Run `alembic -c config/alembic.ini <args>` in host or compose mode.

    host mode: invokes alembic on the developer's machine. `.env` is loaded
        (without overriding already-set vars) so DATABASE_URL flows through
        from the project's `.env` file the way it does for `src.db`.
    compose mode: wraps the invocation via runner.wrap_for_compose so it
        runs inside the named dev service (exec if running, else
        `run --rm --no-deps`). DATABASE_URL is provided by the container env.
    """
    if mode == "host":
        # Lazy-import so compose-only callers don't need python-dotenv on path.
        from dotenv import load_dotenv

        load_dotenv()
    cmd = ["alembic", "-c", ALEMBIC_CONFIG, *args]
    if mode == "compose":
        cmd = runner.wrap_for_compose(service_name, cmd)
    return runner.run_command(cmd)


def _db_is_at_head() -> bool:
    """Return True iff `alembic current` matches `alembic heads` (host mode).

    Loads `.env` so DATABASE_URL is populated the same way `run_alembic`
    sees it. Returns False when the alembic_version table doesn't exist
    yet (fresh DB) — that DB is "behind" head.
    """
    from dotenv import load_dotenv

    load_dotenv()

    def _first_token(stdout: str) -> str:
        for line in stdout.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped.split()[0]
        return ""

    current = subprocess.run(
        ["alembic", "-c", ALEMBIC_CONFIG, "current"],
        capture_output=True,
        text=True,
    )
    heads = subprocess.run(
        ["alembic", "-c", ALEMBIC_CONFIG, "heads"],
        capture_output=True,
        text=True,
    )
    if current.returncode != 0 or heads.returncode != 0:
        return False
    current_token = _first_token(current.stdout)
    heads_token = _first_token(heads.stdout)
    if not current_token or not heads_token:
        return False
    return current_token == heads_token


def generate(runner: "CLIRunner", message: str) -> int:
    """`alembic revision --autogenerate -m <message>` against the host DB."""
    if not _db_is_at_head():
        print(
            "ℹ️ Database is behind head. Run `dev migrate up` first, "
            "then re-run generate.",
            file=sys.stderr,
        )
        return 1
    return run_alembic(
        runner, ["revision", "--autogenerate", "-m", message], mode="host"
    )


def up(runner: "CLIRunner") -> int:
    """`alembic upgrade head` against the host DB."""
    return run_alembic(runner, ["upgrade", "head"], mode="host")


def down(runner: "CLIRunner", steps: int = 1) -> int:
    """`alembic downgrade -<steps>` against the host DB."""
    return run_alembic(runner, ["downgrade", f"-{steps}"], mode="host")


def roundtrip(runner: "CLIRunner", scratch_path: Optional[str] = None) -> int:
    """upgrade head → downgrade -1 → upgrade head against a scratch sqlite DB.

    Defaults to /tmp/bedlam-migrate-roundtrip.db so it can never clobber
    data/app.db. Removes the scratch file on success; leaves it in place on
    failure so the developer can inspect the broken state.
    """
    path = scratch_path or DEFAULT_ROUNDTRIP_SCRATCH
    if os.path.exists(path):
        os.remove(path)

    prior = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    try:
        for args in (["upgrade", "head"], ["downgrade", "-1"], ["upgrade", "head"]):
            rc = run_alembic(runner, args, mode="host")
            if rc != 0:
                return rc
        if os.path.exists(path):
            os.remove(path)
        return 0
    finally:
        if prior is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prior
