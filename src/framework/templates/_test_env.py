"""Shared test-env builder for chrome / view-type / macro template tests.

`make_test_env(...)` stands up a Jinja `Environment` that mirrors the
production env's globals and filters by copying them from
`src.framework.rendering.templating._env`. Test files build envs from
scratch and used to re-register each Jinja global by hand, which meant
adding a new global to `templating.py` cascaded into 4+ test files (the
trigger that broke PR #1264 mid-flight). Sourcing from the prod env
removes that drift surface — new globals show up automatically.

Each call returns a fresh `Environment` so per-test stubs and overrides
don't leak across tests. The stub dict-loader sits in front of the
framework FileSystemLoader so a test can author a child template in
memory that `{% extends "views/list.html" %}` resolves the parent from
the real framework root.
"""

from __future__ import annotations

from typing import Any

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    select_autoescape,
)


def make_test_env(
    stubs: dict[str, str] | None = None,
    **extra_globals: Any,
) -> Environment:
    """Return a Jinja env wired with prod globals + an in-memory stub loader.

    `stubs` seeds the in-memory DictLoader so a test can declare child
    templates ahead of render; callers can also poke
    `env.loader.loaders[0].mapping[name] = body` after construction to
    add more (matches the legacy `_add_child` helper shape).

    `extra_globals` are layered on top of the prod globals — useful for
    per-test fakes (`field_spec=fake_field_spec`, locally-stubbed
    `entity_lock_reason` for branch coverage).
    """
    # Force the domain-side global registration (`capabilities`,
    # per-entity view helpers, etc.) so the snapshot covers everything
    # prod renders with — even when the test runs without the app fixture
    # that would otherwise trigger this import via `src/main.py`.
    import src.domain.template_globals  # noqa: F401
    from src.framework.rendering.templating import _env as _prod_env

    stub_loader = DictLoader(dict(stubs) if stubs else {})
    framework_loader = FileSystemLoader("src/framework/templates")
    env = Environment(
        loader=ChoiceLoader([stub_loader, framework_loader]),
        autoescape=select_autoescape(["html", "xml"]),
    )
    # Mirror prod globals/filters wholesale so a new global registered in
    # `templating.py` flows into every test env without a code change here.
    env.globals.update(_prod_env.globals)
    env.filters.update(_prod_env.filters)
    if extra_globals:
        env.globals.update(extra_globals)
    return env


def add_child(env: Environment, name: str, body: str) -> None:
    """Register a child template body on a test env's stub loader.

    Encapsulates the `env.loader.loaders[0].mapping[name] = body` poke
    so test files don't reach into Jinja loader internals."""
    import textwrap

    env.loader.loaders[0].mapping[name] = textwrap.dedent(body).lstrip()
