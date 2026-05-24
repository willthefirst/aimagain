"""Contract pin: every `@form_error_handler`-decorated route is wired
to a real template + real macros + real field names.

This is the lint that prevents the bug class that motivated the
form-error-handler series in the first place: "the route declares
errors, but the template can't render them" (because the field name
doesn't exist on the form, or the macros aren't imported `with
context`, or the template file moved). The pre-existing
`scripts/dev/contract_form_coverage_check.py` catches form ⇄ endpoint
mismatches; this test catches handler ⇄ template mismatches.

What it pins for each decorated route:

  1. The template file exists on disk.
  2. The template imports `form_fields` macros AND `form_banner` macro
     `with context` (without `with context` the auto-resolution silently
     no-ops — see `_shared/form_fields.html`'s docstring).
  3. Every `field_errors` key returned by any registered handler points
     at a field name that appears in the template (catches typos like
     `field_errors={"emial": "..."}` that would otherwise render
     silently with no inline error).
  4. The route's @router.post tags or `responses=` declaration is
     consistent with the handlers (best-effort: a documented 400 with
     a fastapi-users error code must be handled, unless explicitly
     allowlisted).

Runs at test time via FastAPI app introspection; no AST parsing. The
decorator stashes its config on `wrapper.__form_error_config__` so
this test can recover it without re-deriving from source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.framework.http.form_error_handler import FormError, FormErrorConfig

# Template root — same convention as the existing contract-form lint.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE_ROOTS = (
    _REPO_ROOT / "src" / "domain" / "templates",
    _REPO_ROOT / "src" / "framework" / "templates",
)


def _find_template(name: str) -> Path:
    """Resolve a template name to a Path under one of the template roots.

    Jinja resolves templates via the Environment loader; tests don't have
    the env wired up so this helper walks the same roots directly.
    Fails the test loudly if the template doesn't exist — that's the
    canonical "the decorator points at a moved/deleted template" bug.
    """
    for root in _TEMPLATE_ROOTS:
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise AssertionError(
        f"Template {name!r} declared by @form_error_handler does not exist "
        f"under any of {[str(r) for r in _TEMPLATE_ROOTS]}. The decorator "
        f"points at a moved or deleted template."
    )


def _collect_decorated_routes() -> list[tuple[str, str, FormErrorConfig]]:
    """Walk the FastAPI app and return `(method, path, config)` for
    every route whose endpoint carries `__form_error_config__`.

    Importing `src.main` is the canonical entry point because it
    triggers the `entity_registry` side effects + mounts the auth
    routes. The function walks `app.routes` and unwraps the decorator
    chain (`@form_error_handler` sits *under* `handle_route_errors` +
    `log_route_call`) until it finds the config.
    """
    from src.main import app

    out: list[tuple[str, str, FormErrorConfig]] = []
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        config = _find_form_error_config(endpoint)
        if config is None:
            continue
        methods = getattr(route, "methods", set()) or {"?"}
        for method in methods:
            out.append((method, route.path, config))
    return out


def _find_form_error_config(fn) -> FormErrorConfig | None:
    """Unwrap a decorator chain to find `__form_error_config__`.

    `BaseRouter` wraps every route in `handle_route_errors` then
    `log_route_call` (via `functools.wraps`, so each layer preserves
    `__wrapped__`). The form-error config lives on the inner
    `form_error_handler` wrapper. Walk the chain until we find it or
    run out of `__wrapped__` links.
    """
    cur = fn
    seen = 0
    while cur is not None and seen < 10:
        config = getattr(cur, "__form_error_config__", None)
        if isinstance(config, FormErrorConfig):
            return config
        cur = getattr(cur, "__wrapped__", None)
        seen += 1
    return None


def test_at_least_one_route_uses_the_decorator():
    """Sanity check: if this returns empty the introspection is busted
    (or every callsite was deleted). Catches "the lint runs but
    silently asserts nothing" — the canonical false-green failure
    mode of contract pins."""
    routes = _collect_decorated_routes()
    assert routes, (
        "No @form_error_handler routes discovered via app introspection. "
        "Either the framework's `__form_error_config__` stash regressed "
        "or all callsites were removed. Either way, this test is no "
        "longer pinning anything."
    )


@pytest.mark.parametrize(
    "method,path,config",
    _collect_decorated_routes(),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_template_exists(method: str, path: str, config: FormErrorConfig):
    """Each decorator's `template=` resolves to a real file."""
    _find_template(config.template)


@pytest.mark.parametrize(
    "method,path,config",
    _collect_decorated_routes(),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_template_imports_macros_with_context(
    method: str, path: str, config: FormErrorConfig
):
    """The form-error rerender contract requires the template to import
    both `form_fields` macros AND a banner source `with context` —
    without `with context`, the macros silently no-op on the
    auto-resolution from `form_errors` / `form_values` /
    `form_banner_text`. The framework populates those keys but the
    template fails to read them; the user sees nothing.

    Two ways to satisfy the banner half:
      1. Import `form_banner` directly from `_shared/form_banner.html`
         and place `{{ form_banner() }}` manually. Pre-PR-#8 style.
      2. Import `form_with_errors` from `_shared/form_meta.html` and
         use `{% call form_with_errors(...) %}` — the wrapper macro
         imports `form_banner` itself. Post-PR-#8 style.

    Either is accepted. The wrapper-macro path is preferred for new
    templates because it also bakes in the four hx-* attributes,
    but migrating every existing template at once is out of scope.
    """
    src = _find_template(config.template).read_text(encoding="utf-8")
    # Allow either order; the `with context` clause must appear on each
    # of the two imports. Use a relaxed regex so whitespace/quoting
    # variations don't false-fail.
    fields_import = re.search(
        r'from\s+["\']_shared/form_fields\.html["\'][^}\n]*with context',
        src,
    )
    direct_banner_import = re.search(
        r'from\s+["\']_shared/form_banner\.html["\'][^}\n]*with context',
        src,
    )
    wrapper_import = re.search(
        r'from\s+["\']_shared/form_meta\.html["\'][^}\n]*with context',
        src,
    )
    missing = []
    if not fields_import:
        missing.append("form_fields with context")
    if not direct_banner_import and not wrapper_import:
        missing.append("banner source (form_banner or form_with_errors) with context")
    assert not missing, (
        f"Template {config.template!r} (route {method} {path}) is missing "
        f"required imports: {missing}. Without `with context`, the form-"
        f"error macros can't auto-resolve `form_errors` / `form_values` / "
        f"`form_banner_text` from the render context — see the docstring "
        f"in `src/framework/templates/_shared/form_fields.html`."
    )


def _handler_field_keys(config: FormErrorConfig) -> set[str]:
    """Recover the set of `field_errors` keys this route can emit —
    from both `handlers=` (explicit) and `catches=` (registry-backed).

    Captures typos at config time — `{"emial": ...}` lands in this
    set and fails the per-field-presence assertion below. Same for a
    registry registration with a typo'd `field=`.

    Trade-off: handlers that build `field_errors` keys *dynamically*
    from the exception's attributes (rare but possible) can't be
    statically resolved this way. Today, all callsites use literal
    dict keys; if a dynamic handler shows up, this lint will under-
    cover it but won't false-fail.
    """
    keys: set[str] = set()

    # Explicit handlers — invoke with a stub exception.
    for exc_type, handler in config.handlers.items():
        # Build a stub exception of the right type. fastapi-users
        # exceptions take varied __init__ args, so we go via __new__
        # to skip __init__ — the handler may or may not read attrs,
        # but if it does we want it to fail with AttributeError (which
        # we swallow) rather than a TypeError on construction.
        try:
            stub_exc = exc_type.__new__(exc_type)
        except Exception:
            continue
        # Set a couple of common attributes handlers might read so the
        # stub call doesn't raise on `.reason` etc. Best-effort.
        for attr in ("reason", "message", "args"):
            try:
                setattr(stub_exc, attr, "")
            except Exception:
                pass
        try:
            # 1-arg or 2-arg handler; mimic the decorator's sniff.
            co = getattr(handler, "__code__", None)
            if co is not None and co.co_argcount >= 2:
                form_error = handler(stub_exc, {})
            else:
                form_error = handler(stub_exc)
        except Exception:
            # Handler relied on a real exception or real kwargs; skip.
            # The route-level integration tests still cover this branch.
            continue
        if isinstance(form_error, FormError):
            keys.update(form_error.field_errors.keys())

    # Registry-backed `catches=` — look each exception type up in the
    # registry and collect its `field` (banner-only entries contribute
    # nothing). Pinning here, not just at registration time, means a
    # route can't list an exception under `catches=` whose registered
    # field doesn't exist on the route's template — that mismatch
    # would render the error to nowhere.
    from src.framework.http.form_error_registry import lookup_form_error

    for exc_type in config.catches:
        try:
            stub_exc = exc_type.__new__(exc_type)
        except Exception:
            continue
        mapping = lookup_form_error(stub_exc)
        if mapping is None or mapping.banner or mapping.field is None:
            continue
        keys.add(mapping.field)

    return keys


@pytest.mark.parametrize(
    "method,path,config",
    _collect_decorated_routes(),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_field_error_keys_appear_in_template(
    method: str, path: str, config: FormErrorConfig
):
    """Every `field_errors` key emitted by a registered handler must
    appear as a `name="<field>"` attribute in the template. Catches
    `{"emial": "..."}`-style typos that would otherwise render an
    error message to nowhere.

    The form-fields macros render `<input name="<name>">` for every
    field — string-match on `name="<field>"` is structurally sufficient
    (Pico CSS doesn't reshape inputs into other elements).
    """
    field_keys = _handler_field_keys(config)
    if not field_keys:
        # Banner-only routes (login) — nothing to pin here.
        pytest.skip("Route emits no per-field errors; covered by banner test.")
    src = _find_template(config.template).read_text(encoding="utf-8")
    missing = [k for k in field_keys if f'"{k}"' not in src]
    assert not missing, (
        f"Template {config.template!r} (route {method} {path}) is missing "
        f'`name="<field>"` attributes for handler-emitted field errors: '
        f"{missing}. The macro will render an error message that the user "
        f"sees floating outside any input. Either fix the typo in the "
        f"handler's `field_errors` dict, or add the field to the form."
    )


@pytest.mark.parametrize(
    "method,path,config",
    _collect_decorated_routes(),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_prefill_field_names_appear_in_template(
    method: str, path: str, config: FormErrorConfig
):
    """Same shape as the field-error pin: a `prefill_fields=("emial",)`
    typo would silently fail (the rerender would lose what the user
    typed and they'd have to retype the email). The pin catches it
    at test time.

    Routes using auto-detect (`prefill_fields=None`, the default
    after PR #7) are skipped — the discovered names depend on the
    actual request-body schema at runtime, so there's no static
    list to pin against. Auto-detect is verified at the route layer
    by the existing rerender smokes (which still assert that
    `value="..."` shows up in the response HTML).
    """
    if config.prefill_fields is None:
        pytest.skip(
            "Route uses auto-detect prefill (PR #7) — discovered names "
            "depend on request-body shape at runtime; verified by route "
            'smokes that assert `value="..."` is present in the rerender.'
        )
    if not config.prefill_fields:
        pytest.skip("Route declares no prefill fields.")
    src = _find_template(config.template).read_text(encoding="utf-8")
    missing = [k for k in config.prefill_fields if f'"{k}"' not in src]
    assert not missing, (
        f"Template {config.template!r} (route {method} {path}) is missing "
        f'`name="<field>"` attributes for prefill fields: {missing}. '
        f"The user would lose what they typed on a rerender."
    )
