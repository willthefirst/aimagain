# Background jobs

In-process scheduled work, driven by [APScheduler](https://apscheduler.readthedocs.io/) and started from [`src/main.py`](../main.py)'s `lifespan`.

## Why this directory exists (bucket-grammar deviation)

[`src/README.md`](../README.md) describes a strict two-bucket grammar — `framework/` (domain-agnostic) and `domain/` (entity-specific). `src/jobs/` is a **documented third top-level bucket**, in the same loose-files-at-`src/` category as `main.py`, `db.py`, and `auth_config.py`: app-level glue that is neither domain-specific nor reusable framework.

A job needs:

- A real DB session sharing the production engine and metadata (`async_session_maker` from [`../db.py`](../db.py)).
- The same audit discipline mutation handlers obey: every meaningful state change writes a `record_audit(...)` row in the same transaction as the change.

That's two app-level dependencies plus a scheduler, which doesn't fit cleanly under `framework/` (which knows nothing about specs or domain data) or `domain/<entity>/` (jobs cut across entities).

If a future job's logic is naturally owned by one entity (e.g. nightly verification belongs to providers), the **handler** can live under `src/domain/logic/<entity>/`; this directory just owns the scheduling glue that calls it.

## Rails

Every job in this directory MUST:

1. **Open its own session via `async_session_maker`** — never a FastAPI `Depends`, since there is no request at job-execution time.
2. **Write an audit row** via `record_audit(...)` (or `record_audit_for(...)`/`async with mutate(...)`) for every meaningful state change, then commit. Jobs pass `actor_id=None` — see [System actor](../framework/audit/README.md#system-actor).

The `JOB_RUN_STARTED` action is bespoke (no spec home) — see [`../framework/audit/test_audit_action_drift.py`](../framework/audit/test_audit_action_drift.py).

## Files

- `scheduler.py` — `make_scheduler()` constructs an `AsyncIOScheduler`; `register_jobs(scheduler)` adds every job. Kept separate so tests can introspect registrations without `.start()`-ing.
- `hello_world.py` — smallest job that exercises the rails. Cadence comes from `JOBS_HELLO_WORLD_INTERVAL_MIN` (default `60`); set it to `1` locally to watch the audit row appear.
- `nightly_verification.py` — runs the provider-verification orchestrator (`run_provider_verification` from [`../domain/logic/verifications/handlers.py`](../domain/logic/verifications/handlers.py)) for every non-deleted provider, sequentially, with `actor_id=None`. Schedule comes from `JOBS_NIGHTLY_VERIFICATION_CRON` (default `0 3 * * *` — daily at 03:00 server-local). Per-provider failures are logged and skipped; the loop never re-raises so one bad lookup can't strand the rest of the batch. Each per-provider call commits its own transaction inside the orchestrator.
- `test_*.py` — colocated unit tests per the repo's [definition of done](../../CLAUDE.md#definition-of-done).

## Disabling the scheduler

Set `DISABLE_SCHEDULER=1` to skip `scheduler.start()` in [`../main.py`](../main.py). `register_jobs` still runs so the job table is introspectable; the scheduler simply never fires. The test environment sets this in `.env.test`.

## APScheduler vs system cron

Use APScheduler when a job needs **app rails** — the real `async_session_maker`, audit repository, domain handlers, in-process logging. Use a host-level cron ([`../../deployment/README.md`](../../deployment/README.md)) for jobs that operate outside the app (e.g. `deployment/droplet-files/cleanup-docker.sh` prunes container layers).
