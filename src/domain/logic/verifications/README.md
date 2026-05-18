# Verifications logic cluster

Persistence + pure-function primitives for the provider verification pipeline. The orchestrator (#528) composes them with an `httpx.AsyncClient` it owns.

## Files

- `repository.py` — `VerificationRepository`. Append-only persistence. `record(...)` writes a single attempt; `latest_for_provider(...)` / `list_for_provider(...)` drive the admin UI's per-provider history view. No `update` / `delete` methods by design (see the model README's "Append-only by convention" section).
- `schema.py` — `VerificationRead`, `VerificationCreate`. Both are server-only: there is no public CRUD endpoint; the orchestrator (#528) and the admin readers compose them directly.
- `nppes.py` — `nppes_lookup(npi, *, http)` against the public CMS registry. Errors / timeouts degrade to `NppesResult(found=False, raw=None)` plus a logged warning — never raises.
- `oig.py` — `oig_check(*, first_name, last_name, npi)` against the OIG/LEIE exclusion list (loaded from a CSV on disk). Module-level cache by absolute path; missing CSV degrades to "no match" with a single startup warning.
- `scoring.py` — `score_verification(...)` table-driven rules over `(NppesResult, OigResult, provider name)` → `Score(status, flags, name_match_score)`. No I/O.

(`__init__.py` is intentionally empty — these are imported directly via `src.domain.logic.verifications.nppes`/`.oig`/`.scoring`/`.repository`/`.schema`.)

Issue #528 will add `handlers.py` with the orchestrator + the bespoke trigger endpoint.

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

## System-actor audit pattern

(Preview — full documentation lands with the orchestrator in #528.)

The orchestrator writes the audit row with `actor_id=None` for nightly-job runs (no requesting user) and with `requesting_user.id` for the superuser retrigger endpoint. `AuditLog.actor_id` is nullable for this reason — see [`../../models/verifications/README.md`](../../models/verifications/README.md#system-triggered-runs-and-actor_id).
