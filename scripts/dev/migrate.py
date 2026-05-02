"""
Internal helper for running alembic against this project.

Centralizes the `alembic -c config/alembic.ini ...` invocation so call sites
don't have to spell out the config path or the host-vs-compose distinction.

Step A only exposes `run_alembic`; Step B will add user-facing `dev migrate
generate / up / down / roundtrip` commands on top of this helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from scripts.dev_cli import CLIRunner

ALEMBIC_CONFIG = "config/alembic.ini"
DEFAULT_SERVICE_NAME = "bedlam-connect-dev"


def run_alembic(
    runner: "CLIRunner",
    args: list[str],
    *,
    mode: Literal["host", "compose"],
    service_name: str = DEFAULT_SERVICE_NAME,
) -> int:
    """Run `alembic -c config/alembic.ini <args>` in host or compose mode.

    host mode: invokes alembic on the developer's machine. Caller is
        responsible for ensuring DATABASE_URL is set.
    compose mode: wraps the invocation via runner.wrap_for_compose so it
        runs inside the named dev service (exec if running, else
        `run --rm --no-deps`). DATABASE_URL is provided by the container env.
    """
    cmd = ["alembic", "-c", ALEMBIC_CONFIG, *args]
    if mode == "compose":
        cmd = runner.wrap_for_compose(service_name, cmd)
    return runner.run_command(cmd)
