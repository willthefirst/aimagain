# Verifications cluster

One row per nightly verification attempt against a `Clinician`. Records the outcome the orchestrator (#528) computed: a `status` from `VERIFICATION_STATUSES`, free-form `flags`, the raw NPPES response, an `oig_match` boolean, and an optional NPPES-vs-provider `name_match_score`. Parent-layer conventions (BaseModel inheritance, FK coverage, migrations) live in [`../README.md`](../README.md).

## Append-only by convention

Rows are written and never updated or deleted. The orchestrator only calls `repo.record(...)`; no UI exposes update or delete. The `AuditAction` enum still carries the full `CREATE_VERIFICATION` / `UPDATE_VERIFICATION` / `DELETE_VERIFICATION` triple because `make_audited_resource(...)` requires it as a precondition, but only `CREATE_VERIFICATION` ever fires — see `_BESPOKE` in [`src/framework/audit/test_audit_action_drift.py`](../../../framework/audit/test_audit_action_drift.py) for the rationale.

## Two callers, two `actor_id`s

The nightly job (#530) runs with `actor_id=None` (see [System actor](../../../framework/audit/README.md#system-actor)); the superuser-only retrigger endpoint (#528) writes the requesting user's id. The orchestrator composes both — see [`../../logic/verifications/handlers.py`](../../logic/verifications/handlers.py).
