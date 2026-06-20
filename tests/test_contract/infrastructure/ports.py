"""Ephemeral free-port allocation for contract-test servers.

A contract session binds several local servers: one consumer server, one
provider server per provider, and one Pact mock service per consumer test
(the mock services accumulate — pact-python tears them down at process exit,
not between tests). Historically each of these used a hardcoded port
(consumer 8990, provider 8999, and a per-pair Pact port). Hardcoded ports are
machine-global, so a second contract session anywhere on the same host — e.g.
a parallel agent worktree — collides on them, surfacing as misleading
Playwright selector timeouts rather than an obvious bind error.

Allocating OS-assigned free ports instead lets contract sessions run
concurrently and removes the within-session re-bind race entirely. See
`tests/test_contract/README.md#running`.

`find_free_port` binds to port 0, reads back the kernel-assigned port, and
closes the probe socket. There is a small TOCTOU window between the probe
closing and the real server binding; in practice it is negligible because the
ports are in the high ephemeral range and the bind follows immediately, and
any already-bound Pact service's port is never re-offered by the kernel.
"""

import socket


def find_free_port(host: str = "127.0.0.1") -> int:
    """Return a currently-free TCP port on `host`, assigned by the OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]
