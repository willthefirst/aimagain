# Working in this repo

This file is the contract between you (the AI agent) and this codebase. Read it before any code change.

## Architecture in one line

The code under `src/` is organized by **layer**, not by feature: `api/`, `services/`, `repositories/`, `models/`, `schemas/`, `logic/`, `middleware/`, `core/`, `templates/`. A new entity (e.g. a `Widget`) typically touches every layer. See [`src/README.md`](src/README.md) for layer responsibilities and the dependency rules between them.

## Definition of done

For any code change in `src/<layer>/`, the change is **not done** until all four are true:

1. The code change itself is in.
2. The colocated `src/<layer>/README.md` reflects new/changed/removed behavior — or you have explicitly verified it is still accurate.
3. The colocated test file (`src/<layer>/test_*.py`) is updated or added to cover the change.
4. `dev test` passes and `dev lint` passes.

If a layer has no README or no test file yet, **create them as part of the change**. Don't defer.

A Stop hook checks the diff at end-of-turn and surfaces a reminder when source files change without their README/test. The hook is a soft prompt, not a hard block — but ignoring it should be a deliberate decision (e.g. typo fix, log message tweak), not an oversight.

## One source of truth — link, don't copy

Each fact has exactly **one home**: the README closest to the code or config that the fact describes. Other docs link to it; they never restate it.

- The CLI's command list lives in [`scripts/README.md`](scripts/README.md). Every other doc that wants to mention a command links there.
- The layered architecture lives in [`src/README.md`](src/README.md). The root README and layer READMEs link there, not duplicate it.
- A layer's behavior, conventions, and tests live in `src/<layer>/README.md`. Cross-references go upward via links.
- Migrations live in [`alembic/README.md`](alembic/README.md). Deployment in [`deployment/README.md`](deployment/README.md). Testing conventions in [`tests/README.md`](tests/README.md).

If you find a fact stated in two places, **one of them is wrong** — even if both currently agree, they will drift. Pick the one closest to the code, leave it there, and replace the other with a link. The Stop hook only catches drift between code and its colocated README/test; cross-cutting drift (e.g. CLI commands documented in the root README) can only be prevented by not duplicating in the first place.

## Where to look

| Topic | Where it lives |
| --- | --- |
| Architecture, layer responsibilities, dependency rules | [`src/README.md`](src/README.md) |
| Resource URL grammar, lifecycle, subresource conventions | [`src/api/routes/RESOURCE_GRAMMAR.md`](src/api/routes/RESOURCE_GRAMMAR.md) |
| CLI commands (`dev ...`) | [`scripts/README.md`](scripts/README.md) |
| Testing conventions, fixtures | [`tests/README.md`](tests/README.md) |
| Database migrations | [`alembic/README.md`](alembic/README.md) |
| Deployment | [`deployment/README.md`](deployment/README.md) |
| A specific layer's behavior | `src/<layer>/README.md` |

Pre-commit hooks run lint automatically — don't bypass with `--no-verify`.

## When in doubt

1. Read [`src/README.md`](src/README.md) for layer responsibilities and what may import what.
2. Read the README of the layer you're changing, plus the layers it depends on.
3. If a single change forces edits across most layers (model + schema + repo + service + route), follow the entity checklist in [`src/README.md`](src/README.md#adding-a-new-domain-entity) — that's expected for new entities, not a smell.
4. **Before adding or modifying a resource type** (new entity, new endpoint, new lifecycle behavior, new permission rule), read [`src/api/routes/RESOURCE_GRAMMAR.md`](src/api/routes/RESOURCE_GRAMMAR.md) first. That document is the prescriptive contract for URL shape, lifecycle states, and subresource conventions; every resource conforms to it.
5. **Before adding or moving a route**, run `dev routes` (optionally with a path prefix, e.g. `dev routes /users`) to see every handler currently mounted. Catches router shadowing — when two `include_router` calls register handlers for overlapping paths and the second is silently ignored — before tests do.

## Implementation notes that aren't obvious from the code

- **Sessions are not auto-committed.** `get_db_session` (in `src/db.py`) yields a session that the caller must `await session.commit()` after writes. Currently the *logic* layer holds that responsibility because the *services* layer is mostly empty stubs; if you populate a service, move the commit there and update [`src/README.md`](src/README.md) so the layer matrix matches reality.
- **`fastapi-users` does not own `/users/{id}`.** The built-in users router was removed; `src/api/routes/users.py` and `src/api/routes/me.py` together own the `/users/*` surface. `me` MUST be registered before `users` in `src/main.py` so `/users/me` matches the literal handler before being interpreted as a UUID.

## When to use plan mode

- **Use** `/plan` for changes that span multiple layers, introduce new resources/routes, change lifecycle, or otherwise need a written-down design. The Explore + Plan workflow earns its overhead when the cost of a wrong direction is high.
- **Skip** `/plan` for typo fixes, log-message tweaks, single-file refactors, README polish, dependency bumps. Just do the change. Plan-mode overhead on small changes wastes a turn.
- When in doubt: if you can describe the change in one sentence and it touches one file, skip plan mode.

## Per-PR retrospective

Before declaring a PR complete (after the final commit but before pushing or summarizing), run a retrospective on the session that produced it. The goal is to surface friction the next agent should not have to re-discover — and, eventually, to feed a queue of GitHub issues that agents themselves can resolve.

For each pain point, write a short structured entry suitable for becoming a GitHub issue:

```
### <one-line title — issue title>
**Friction:** what slowed me down or caused rework, with a concrete example.
**Fix:** the specific change that would prevent it next time (file, command, config).
**Effort:** small / medium / large.
```

Cover at least:

- The single biggest time sink in the session and its root cause.
- Any tool, doc, or convention that was missing or misleading (often the cause of the time sink).
- Anything that worked unexpectedly well and should be made explicit so it gets repeated.

Ship the retro back to the user as the final message of the session, separately from the PR description. They decide which entries get filed as issues.
