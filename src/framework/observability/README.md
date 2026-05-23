# Observability: provider-agnostic error tracking + tracing

A thin abstraction over whatever error-tracking / APM SaaS the app is wired to. The only file that imports a provider SDK is the matching `*_backend.py` — every other call site goes through `observability` from this package.

## Files

- `backend.py` — the `ObservabilityBackend` `Protocol`. Three methods: `init_app(app)`, `set_user(user_id, email)`, `frontend_context()`.
- `sentry_backend.py` — the Sentry implementation. Reads sample rates, release tag, and PII flags from `settings`.
- `noop_backend.py` — selected when no DSN is set. Lets call sites drop the `if settings.X` guard.
- `__init__.py` — exposes `observability`, the module-level singleton chosen by `_select_backend()` from settings.

## Call sites

- **Init** — `src/main.py` calls `observability.init_app(app)` once during FastAPI construction.
- **User tagging** — the wrapping deps `current_active_user` / `current_admin_user` / `current_optional_user` in `src/auth_config.py` call `observability.set_user(...)` during request handling. Tagging from middleware after `call_next` is too late — exceptions raised inside the handler are already captured by then.
- **Browser SDK** — `src/framework/rendering/templating.py:get_template_context` puts `observability.frontend_context()` into every render as `observability_frontend`; `src/framework/templates/base.html` branches on `observability_frontend.provider` and renders the right `<script>` block.

## Adding a new provider

1. Add `<name>_backend.py` with a class that satisfies `ObservabilityBackend`.
2. Add a branch in `_select_backend()` in `__init__.py` keyed off a new (or existing) setting.
3. Add a `{% elif observability_frontend.provider == "<name>" %}` block in `base.html` with that provider's browser SDK init.
4. Add tests in `test_<name>_backend.py`.

No other file should need to change. If a call site needs something the contract doesn't expose, extend `backend.py` first (and update every existing backend) — never special-case a provider at a call site.

## Settings

All provider knobs live in `src/framework/config.py` with sensible production defaults:

- `SENTRY_DSN` — empty disables the provider entirely (Noop backend selected).
- `SENTRY_TRACES_SAMPLE_RATE` (default `0.1`).
- `SENTRY_PROFILES_SAMPLE_RATE` (default `0.1`).
- `SENTRY_REPLAY_SAMPLE_RATE`, `SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE` (default `0.0` / `0.0` — Replay opt-in).
- `APP_RELEASE` — git SHA injected at deploy time. Provider-agnostic name; consumed by every backend that supports a release tag.

## Tests

`test_backend.py`, `test_sentry_backend.py`, `test_noop_backend.py` — one per module. The Sentry test patches `sentry_sdk` rather than calling the real SDK.
