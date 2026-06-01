# Verifications cluster

One row per verification attempt against a `Clinician` or `Organization`. Records the outcome the orchestrator computed: a `status` from `VERIFICATION_STATUSES`, free-form `flags`, the raw NPPES response, an `oig_match` boolean, and an optional NPPES-vs-subject `name_match_score`. Parent-layer conventions (BaseModel inheritance, FK coverage, migrations) live in [`../README.md`](../README.md).

## Append-only by convention

Rows are written and never updated or deleted. The orchestrator only calls `repo.record(...)`; no UI exposes update or delete. The `AuditAction` enum still carries the full `CREATE_VERIFICATION` / `UPDATE_VERIFICATION` / `DELETE_VERIFICATION` triple because `make_audited_resource(...)` requires it as a precondition, but only `CREATE_VERIFICATION` ever fires — see `_BESPOKE` in [`src/framework/audit/test_audit_action_drift.py`](../../../framework/audit/test_audit_action_drift.py) for the rationale.

## Callers and `actor_id`

The inline NPI-submit routes ([`../../routes/verifications.py`](../../routes/verifications.py)) and the superuser-only retrigger endpoint both pass `actor_id=requesting_user.id`. The orchestrator still accepts `actor_id=None` for system-initiated runs (see [System actor](../../../framework/audit/README.md#system-actor)) — kept for future use even though no caller passes it today. Orchestrator lives in [`../../logic/verifications/handlers.py`](../../logic/verifications/handlers.py).
