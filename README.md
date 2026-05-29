# Bedlam Connect

FastAPI + server-side rendering + HTMX, with JWT cookie auth via fastapi-users. Python 3.11+; SQLite locally, Postgres in production; Docker-based dev and deploy.

## Quick start

```bash
pip install -e .          # installs the project + the `dev` CLI
dev setup                 # creates .env and the local database
dev up                    # starts the dev server at http://localhost:8000
dev test                  # runs the test suite
```

`dev --help` lists every command. See [`scripts/README.md`](scripts/README.md) for what's there, including `dev merge <PR#>` for shepherding a PR through Mergify's queue.

### Dev auto-login

After `dev seed` populates the seed admin user, bookmark:

```
http://localhost:8000/dev/login-as-seed-user
```

Hitting it issues the same session cookie a real login would (for the user named by `DEV_LOGIN_EMAIL`, defaulting to `admin@example.com`) and redirects to `/`, which forwards to the current default landing page (today: `/posts?kind=referral` — the single whole-supertype `/posts` family narrowed via the `?kind=` query). Saves a form submission every time you reopen the browser to the dev server. The route is only mounted when `ENVIRONMENT=development` — production never registers it. See [`src/domain/routes/dev_auth.py`](src/domain/routes/dev_auth.py) for the security guards.

### Playwright MCP for design review

Claude Code can drive a real browser against the dev server to navigate, click, resize, and screenshot — useful for "load `/posts?kind=clinician_opening` at iPhone width and check the location row" tasks. The MCP entry is pre-configured in [`.claude/settings.json`](.claude/settings.json); the one-time browser install is:

```bash
dev playwright-setup      # installs Chromium (~150MB)
```

After that, restart Claude Code. The agent navigates to `/dev/login-as-seed-user` as its first tool call and proceeds authenticated.

## Documentation map

Each fact lives in the README closest to the code that defines it; other docs link to it. See [`CLAUDE.md`](CLAUDE.md) for the contract.

- [`CLAUDE.md`](CLAUDE.md) — agent/contributor contract: definition of done, doc/test/code coupling.
- [`src/README.md`](src/README.md) — application architecture, layer responsibilities, import discipline.
- [`src/domain/routes/RESOURCE_GRAMMAR.md`](src/domain/routes/RESOURCE_GRAMMAR.md) — URL shape, lifecycle, subresource conventions. Read before adding a resource.
- [`tests/README.md`](tests/README.md) — testing conventions and shared fixtures.
- [`alembic/README.md`](alembic/README.md) — database migrations.
- [`deployment/README.md`](deployment/README.md) — deployment + bootstrapping the first admin.
