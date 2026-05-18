# Verifications cluster

One model: `Verification`. The parent layer's conventions (BaseModel inheritance, FK-relationship coverage, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to the verifications cluster.

A `Verification` is one row per nightly verification attempt against a `Provider`. It records the outcome the orchestrator (issue A4 / #528) computed: a `status` from `VERIFICATION_STATUSES`, free-form `flags`, the raw NPPES response (`nppes_result`), an `oig_match` boolean, and an optional NPPES-vs-provider `name_match_score`.

## Append-only by convention

Rows are written and never updated or deleted. The orchestrator only calls `repo.record(...)`; no UI exposes update or delete. The `AuditAction` enum still carries the full `CREATE_VERIFICATION` / `UPDATE_VERIFICATION` / `DELETE_VERIFICATION` triple because `make_audited_resource(...)` requires it as a precondition, but only `CREATE_VERIFICATION` ever fires — see `_BESPOKE` in [`src/framework/audit/test_audit_action_drift.py`](../../../framework/audit/test_audit_action_drift.py) for the rationale.

## System-triggered runs and `actor_id`

The nightly job (#530) runs with no requesting user; the verification's audit row is written with `actor_id=None`. `AuditLog.actor_id` is `nullable=True` with `ON DELETE SET NULL` ([`src/framework/audit/log.py`](../../../framework/audit/log.py)), so this is legal at the DB layer. The superuser-only retrigger endpoint (#528) writes the requesting user's id instead. The orchestrator's audit composition lives in [`../../logic/verifications/handlers.py`](../../logic/verifications/handlers.py) — see that file for the full ritual.
