# Verifications logic cluster

Persistence + pure-function primitives for the provider verification pipeline. The orchestrator (#528) composes them with an `httpx.AsyncClient` it owns.

## Files

- `repository.py` — `VerificationRepository`. Append-only persistence. `record(...)` writes a single attempt; `latest_for_provider(...)` / `list_for_provider(...)` drive the admin UI's per-provider history view. No `update` / `delete` methods by design (see the model README's "Append-only by convention" section).
- `schema.py` — `VerificationRead`, `VerificationCreate`. Both are server-only: there is no public CRUD endpoint; the orchestrator (#528) and the admin readers compose them directly.
- `nppes.py` — `nppes_lookup(npi, *, http)` against the public CMS registry. Errors / timeouts degrade to `NppesResult(found=False, raw=None)` plus a logged warning — never raises.
- `oig.py` — `oig_check(*, first_name, last_name, npi)` against the OIG/LEIE exclusion list (loaded from a CSV on disk). Module-level cache by absolute path; missing CSV degrades to "no match" with a single startup warning.
- `scoring.py` — `score_verification(...)` table-driven rules over `(NppesResult, OigResult, provider name)` → `Score(status, flags, name_match_score)`. No I/O.
- `handlers.py` — `run_provider_verification(...)` orchestrator + `handle_create_provider_verification(...)` admin-only retrigger. Composes the primitives with persistence + audit + an `httpx.AsyncClient`. The bespoke route lives at [`../../routes/verifications.py`](../../routes/verifications.py) and is wired into `src/main.py` next to the other hand-rolled routers.

The orchestrator has three callers:

1. **`handle_create_provider_verification`** in this file (admin retrigger; `actor_id=requesting_user.id`).
2. **`run_nightly_verification`** in [`../../../jobs/nightly_verification.py`](../../../jobs/nightly_verification.py) (daily APScheduler job; `actor_id=None`).
3. **`verify_and_create_clinician`** in [`../../logic/onboarding/services.py`](../onboarding/services.py) (self-service wizard path; `actor_id=user.id`).

(`__init__.py` is intentionally empty — these are imported directly via `src.domain.logic.verifications.nppes`/`.oig`/`.scoring`/`.repository`/`.schema`/`.handlers`.)

## Why pure functions, not classes

The orchestrator owns the database session and the `httpx.AsyncClient` — pure functions take those as parameters so the test surface is the function itself, not a class with constructor wiring. The orchestrator (#528) holds the lifecycle; these modules hold the rules.

## Registry rate limits and reliability

NPPES is a free public registry; no documented rate limit. The nightly job (#530) runs sequentially anyway, so we don't pace requests. The 10-second per-call timeout exists so a single hung lookup can't stall the whole batch.

## Exclusion-list refresh cadence

The OIG publishes a fresh LEIE CSV on the first business day of each month at https://oig.hhs.gov/exclusions/exclusions_list.asp. Operator refresh:

1. Download the "Updated LEIE Database" CSV.
2. Replace `data/LEIE.csv` on the host (`LEIE_CSV_PATH` env var overrides).
3. Restart the process so the in-memory cache reloads — the cache is keyed by absolute path and built on first access; there is no hot-reload signal.

A missing CSV does not crash the pipeline — `oig_check` logs once at process startup and returns "no match" for every check. The scoring layer's `verified` outcome therefore still requires the NPPES side to succeed, so a missing LEIE never falsely escalates a row to `verified`; it merely degrades the OIG check to a no-op.

## Audit ritual

The orchestrator writes one `Verification` row plus one matching audit row in a single transaction (`record_audit_for(...)` + an explicit `session.commit()`). `actor_id=None` for nightly runs, `requesting_user.id` for the admin retrigger — see [System actor](../../../framework/audit/README.md#system-actor). The retrigger endpoint is `current_admin_user`-gated; non-superusers get 403.

### Why `record_audit_for` + explicit commit (not `mutate`)

The `mutate(...)` context manager is a snapshot-before / mutate / record_audit / commit ritual built around a pre-existing target — it snapshots `before` from the row that's already in the DB. Verification rows are *created* each run, so there's no pre-existing target. `record_audit_for` plus an explicit commit matches the favorites cluster's edge-add/remove pattern (`src/domain/logic/favorites/handlers.py`), which has the same shape (no pre-existing target on add).

### Dev/test fallback (`BEDLAM_VERIFY_DEV_FALLBACK`)

Set `BEDLAM_VERIFY_DEV_FALLBACK=1` to skip the real NPPES network call and synthesize an NPPES hit that matches the provider's own names (name-similarity = 1.0 → `verified`). Only for local dev and integration tests; never set in production. The OIG check still runs (using the configured CSV path).

### Name fields gap (followup tracking)

`run_provider_verification` reads provider names via `_provider_names(provider)`, which falls back to `user.username` in the first-name slot because the `User` model has no `first_name` / `last_name` columns today. The scoring layer's similarity check lands far below threshold against the NPPES first/last names, so every verification routes to `needs_review` until proper name fields are added. The safe default is on purpose: a human reviewer confirms identity rather than the pipeline auto-verifying against a name we never actually had. Adding `first_name` / `last_name` to `User` is a separate ticket.

### Intake post-create hook

Triggering verification automatically after `POST /providers` succeeds was scoped out of this PR per #528 — the framework's CRUD handler doesn't have a `post_create_hook`, and adding one to the dispatcher is more scope than #528 should carry. Track as a follow-up issue.
