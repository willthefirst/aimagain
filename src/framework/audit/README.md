# Audit: append-only mutation record

Append-only mutation record per [`../../domain/routes/RESOURCE_GRAMMAR.md`](../../domain/routes/RESOURCE_GRAMMAR.md). Every mutation handler MUST write an audit row in the same transaction as the mutation; the `test_audit_discipline.py` static check enforces this at CI time.

## The contract

Every mutation handler does one of:

```python
# Option 1: bare helper, used by non-CRUD mutations (register, set-activation).
await record_audit(audit_repo, actor_id=..., resource_type=..., resource_id=...,
                   action=..., before=..., after=...)
await repo.session.commit()

# Option 2: resource-flavored helper for handlers that don't fit the
# snapshot/mutate/audit/commit ritual.
await record_audit_for(audit_repo, actor=..., target=..., resource=R, verb="update")
await repo.session.commit()

# Option 3: the context manager that owns the whole ritual.
async with mutate(repo, audit_repo, actor=..., target=..., resource=R, verb="update"):
    await repo.update_X(target, ...)
```

The discipline check accepts any of the three. If a handler `commit`s without one of those names appearing in its body, the test fails with a pointer to RESOURCE_GRAMMAR.md.

## Files

- `core.py` — `AuditAction` enum, `AuditedResource` / `EdgeAudit` dataclasses, `record_audit`, `record_audit_for`, the `mutate(...)` context manager, `make_audited_resource(...)` factory, `make_snapshotter(...)`.
- `log.py` — the `AuditLog` SQLAlchemy model (append-only; FK to `users.id` with `SET NULL`; `(resource_type, resource_id)` lookups).
- `repository.py` — `AuditRepository`, deliberately exposing only writes + read-by-id. No `update_*` / `delete_*` — audit rows are immutable.

## The discipline check

`test_audit_discipline.py` parses each `handlers.py` under `src/domain/` (recursively), walks every `async def handle_*` function, and fails the test if the function calls `.commit()` without an audit-recording call. Opt-out: add `audit-discipline-ignore` to the function's docstring with a brief reason. Use sparingly.

## Tests

`test_core.py`, `test_repository.py`, `test_audit_discipline.py`, `test_audit_action_drift.py` (asserts every spec's audit binding has the expected `CREATE_<STEM>` / `UPDATE_<STEM>` / `DELETE_<STEM>` triple).
