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


def generate(runner: "CLIRunner", message: str) -> int:
    """`alembic revision --autogenerate -m <message>` against the host DB."""
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
