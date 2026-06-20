"""Tests for the ephemeral free-port allocator."""

import socket

from tests.test_contract.infrastructure.ports import find_free_port


def test_find_free_port_returns_a_bindable_port():
    """The returned port is actually free — we can bind it ourselves."""
    port = find_free_port()
    assert isinstance(port, int)
    assert 1024 < port <= 65535
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))  # would raise OSError if not free


def test_find_free_port_skips_a_bound_port():
    """A port already bound by a live socket is never handed back — this is
    the property that lets accumulating Pact mock services coexist."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        taken = held.getsockname()[1]
        for _ in range(20):
            assert find_free_port() != taken
