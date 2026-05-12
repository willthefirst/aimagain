# Alembic: Database migration management

Database migrations live here. Day-to-day operations go through the `dev migrate` wrappers (`generate`, `up`, `down`, `roundtrip`) — see `dev migrate --help` for what each does. Raw `alembic` is still available for introspection commands without a wrapper (e.g. `alembic -c config/alembic.ini current`, `alembic ... history`).

## Layout

- `env.py` — migration environment. Reads `DATABASE_URL` from the env, normalizes async URLs to sync for Alembic compatibility (`sqlite+aiosqlite://` → `sqlite://`, `postgresql+asyncpg://` → `postgresql://`), imports `metadata` from `src.domain.models` for autogeneration. Errors loudly if `DATABASE_URL` is unset and no URL is configured in `alembic.ini`.
- `script.py.mako` — Alembic's stock migration template.
- `versions/` — migration files. `ls alembic/versions/` is the source of truth for what's been applied.
- `../config/alembic.ini` — Alembic configuration (database URL, logging, file paths).

## Authoring a migration

1. Make model changes under `src/domain/models/`.
2. `dev migrate generate "<message>"` — runs `alembic revision --autogenerate`. Autogenerate isn't perfect; **review the generated file under `versions/` before applying**.
3. `dev migrate roundtrip` — sanity-checks upgrade → downgrade → upgrade against a throwaway sqlite DB. Catches "downgrade doesn't reverse my upgrade" and "the migration crashes on a fresh DB" before either reaches main.
4. `dev migrate up` — applies against the host DB.
5. Commit the generated file alongside the model change.

## Conventions

- **Schema only, not data.** Migrations change shape; data backfills go in separate scripts or in subsequent migrations explicitly authored to mutate data.
- **Reversible by default.** A `downgrade()` that drops a column with data is data loss. For column removals or destructive changes, use a two-step migration: add-new + backfill, then a follow-up that removes-old after the backfill is verified.
- **Descriptive messages.** `dev migrate generate "add user email_verified column"` beats `"changes"` — the message becomes the file name.
- **Dropping a CHECK-constrained column on SQLite needs `batch_alter_table`.** A plain `op.drop_column(...)` against a column referenced by a named CHECK constraint will fail with `error in table … after drop column: no such column: <name>`. Wrap the drop in `with op.batch_alter_table(table) as batch_op:` and call `batch_op.drop_constraint("<ck_name>", type_="check")` + `batch_op.drop_column(...)` together — SQLite then rewrites the table cleanly. Examples: revisions `2bed07fb1d76`, `6e7b42cd3894`.

## Production deployment

`scripts/runtime/start.sh` runs `alembic upgrade head` before starting the FastAPI app, so deploying a new revision applies it on container start. See [`deployment/README.md`](../deployment/README.md) for the full deploy flow.

## Related documentation

- [`src/domain/models/README.md`](../src/domain/models/README.md) — models that drive autogeneration.
- [`src/db.py`](../src/db.py) — runtime database configuration.
