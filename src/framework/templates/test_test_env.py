"""Tests for the shared chrome-test env builder (`_test_env.py`).

The helper's contract is "prod-mirror": a Jinja env returned by
`make_test_env()` exposes the same globals + filters as the production
`templating._env`. The chrome / view-type / macro tests rely on that
invariant to render real templates without re-registering each global
by hand. If a new global is added to `templating.py` (or via
`register_template_globals` from `template_globals.py`), it must show
up here automatically — that's the surface this test guards.
"""

from __future__ import annotations

from src.framework.rendering.templating import _env as _prod_env
from src.framework.templates._test_env import add_child, make_test_env


def test_mirrors_prod_globals():
    """Every prod global must appear in the test env. New globals added
    to `templating.py` (or via `register_template_globals`) flow in
    automatically — no per-test edit required."""
    env = make_test_env()
    for name in _prod_env.globals:
        assert name in env.globals, f"prod global {name!r} missing from test env"


def test_mirrors_prod_filters():
    """Same prod-mirror contract for `_env.filters` (`format_post_date`,
    `days_ago`)."""
    env = make_test_env()
    for name in _prod_env.filters:
        assert name in env.filters, f"prod filter {name!r} missing from test env"


def test_capabilities_global_is_registered_without_app_boot():
    """`capabilities` is registered by `domain/template_globals.py`,
    which is imported by `src/main.py` at app boot. The helper forces
    that import so chrome tests running in isolation (no app fixture)
    still see the domain-side globals."""
    env = make_test_env()
    assert "capabilities" in env.globals
    # And the resolved namespace exposes the REASON_* constants used by
    # the locked-affordance macros.
    assert env.globals["capabilities"].REASON_NETWORK_UNVERIFIED == "network_unverified"


def test_extra_globals_layer_over_prod_globals():
    """Per-test fakes (`field_spec=fake_field_spec`, stub
    `entity_lock_reason`) override the prod-mirrored value."""
    sentinel = object()
    env = make_test_env(field_spec=sentinel)
    assert env.globals["field_spec"] is sentinel


def test_stubs_seed_dict_loader():
    """Templates passed via `stubs=` resolve through the stub loader
    before the framework FileSystemLoader."""
    env = make_test_env(stubs={"child.html": "hello {{ who }}"})
    out = env.get_template("child.html").render(who="world")
    assert out == "hello world"


def test_add_child_pokes_loader_after_construction():
    """The legacy `_add_child(env, name, body)` shape still works —
    test bodies that add stubs lazily continue to."""
    env = make_test_env()
    add_child(env, "child.html", "value={{ v }}")
    out = env.get_template("child.html").render(v=42)
    assert out == "value=42"


def test_each_env_is_independent():
    """Two envs from the same helper call don't share stub state."""
    a = make_test_env()
    b = make_test_env()
    add_child(a, "x.html", "from-a")
    assert "x.html" not in b.loader.loaders[0].mapping
