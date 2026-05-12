# Bedlam CONNECT

FastAPI + server-side rendering + HTMX, with JWT cookie auth via fastapi-users. Python 3.11+; SQLite locally, Postgres in production; Docker-based dev and deploy.

## Quick start

```bash
pip install -e .          # installs the project + the `dev` CLI
dev setup                 # creates .env and the local database
dev up                    # starts the dev server at http://localhost:8000
dev test                  # runs the test suite
```

`dev --help` lists every command. See [`scripts/README.md`](scripts/README.md) for what's there.

## Documentation map

Each fact lives in the README closest to the code that defines it; other docs link to it. See [`CLAUDE.md`](CLAUDE.md) for the contract.

- [`CLAUDE.md`](CLAUDE.md) — agent/contributor contract: definition of done, doc/test/code coupling.
- [`src/README.md`](src/README.md) — application architecture, layer responsibilities, import discipline.
- [`src/domain/routes/RESOURCE_GRAMMAR.md`](src/domain/routes/RESOURCE_GRAMMAR.md) — URL shape, lifecycle, subresource conventions. Read before adding a resource.
- [`tests/README.md`](tests/README.md) — testing conventions and shared fixtures.
- [`alembic/README.md`](alembic/README.md) — database migrations.
- [`deployment/README.md`](deployment/README.md) — deployment + bootstrapping the first admin.
