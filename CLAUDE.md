# Working in this repo

This file is the contract between you (the AI agent) and this codebase. Read it before any code change.

## Definition of done

For any code change in `src/<module>/`, the change is **not done** until all four are true:

1. The code change itself is in.
2. The colocated `src/<module>/README.md` reflects new/changed/removed behavior — or you have explicitly verified it is still accurate.
3. The colocated test file (`src/<module>/test_*.py`) is updated or added to cover the change.
4. `dev test` passes and `dev lint` passes.

If a module has no README or no test file yet, **create them as part of the change**. Don't defer.

A Stop hook checks the diff at end-of-turn and surfaces a reminder when source files change without their README/test. The hook is a soft prompt, not a hard block — but ignoring it should be a deliberate decision (e.g. typo fix, log message tweak), not an oversight.

## One source of truth — link, don't copy

Each fact has exactly **one home**: the README closest to the code or config that the fact describes. Other docs link to it; they never restate it.

- The CLI's command list lives in [`scripts/README.md`](scripts/README.md). Every other doc that wants to mention a command links there.
- The layered architecture lives in [`src/README.md`](src/README.md). The root README and module READMEs link there, not duplicate it.
- A module's behavior, conventions, and tests live in `src/<module>/README.md`. Cross-references go upward via links.
- Migrations live in [`alembic/README.md`](alembic/README.md). Deployment in [`deployment/README.md`](deployment/README.md). Testing conventions in [`tests/README.md`](tests/README.md).

If you find a fact stated in two places, **one of them is wrong** — even if both currently agree, they will drift. Pick the one closest to the code, leave it there, and replace the other with a link. The Stop hook only catches drift between code and its colocated README/test; cross-cutting drift (e.g. CLI commands documented in the root README) can only be prevented by not duplicating in the first place.

## Module locality

When changing code in module X, prefer reading only `src/X/` and its direct dependencies (the layers below it).

If you find yourself reading 3+ unrelated modules to make a single local change, **stop and tell the user** — the module boundary is probably wrong, and that's worth fixing before continuing.

## Where to look

| Topic | Where it lives |
| --- | --- |
| Architecture, layer responsibilities | [`src/README.md`](src/README.md) |
| CLI commands (`dev ...`) | [`scripts/README.md`](scripts/README.md) |
| Testing conventions, fixtures | [`tests/README.md`](tests/README.md) |
| Database migrations | [`alembic/README.md`](alembic/README.md) |
| Deployment | [`deployment/README.md`](deployment/README.md) |
| A specific module's behavior | `src/<module>/README.md` |

Pre-commit hooks run lint automatically — don't bypass with `--no-verify`.

## When in doubt

1. Read the module's own README first.
2. Then `src/README.md` for layer responsibilities.
3. Then ask the user before reaching across many modules.
