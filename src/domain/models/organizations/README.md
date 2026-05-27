# Organizations cluster

First-class directory entity for clinics, group practices, health systems, and solo-practice shells. PR 2 of the Org/Program roadmap (#520) wired Clinician to Organization via an `org_id` FK on the former `providers` table; in #635 PR B that FK moved to `affiliations.org_id` (along with the rest of the per-role columns), so the Org→Clinician path now navigates `affiliations` rather than a back-relationship on this table.

The parent layer's conventions (BaseModel inheritance, FK CASCADE, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to organizations.

## Files

- `organization.py` — `Organization`. Hierarchy via a nullable self-FK `parent_org_id` and a denormalized non-nullable `root_org_id`. Tied to a `User` via non-unique `owner_id` FK + CASCADE (one user may own many orgs). Enum column `type` CHECKs against `ORGANIZATION_TYPES` from [`../enums.py`](../enums.py). The Org→Clinician direction is reached through `Affiliation.org_id` (RESTRICT — deleting an Org with attached Affiliations fails loudly); there is no `Organization.clinicians` back-relationship. The `Organization.programs` collection (RESTRICT) remains for the Program child.

## The `parent_org_id` + `root_org_id` invariant

`Organization` is a tree. Two columns carry that:

- `parent_org_id` — the **immediate** parent. `NULL` for a root.
- `root_org_id` — the **subtree root**: the topmost ancestor in the tree. For a root, `root_org_id = id` (the row is its own root). For a non-root, `root_org_id = parent.root_org_id`.

The second column is a denormalization: it lets queries like "every org under health-system X" be a single indexed read (`WHERE root_org_id = X`) instead of a recursive CTE.

**The invariant the writer MUST hold on insert and on any `parent_org_id` change:**

```
root_org_id = (id if parent_org_id IS NULL else parent.root_org_id)
```

Today only `Organization` itself writes the table, so the invariant is enforced in `src/domain/logic/organizations/repository.py` (`create`). When PR 2+ widens write paths, every writer MUST apply the same rule — or move the rule into a DB trigger. There is no `CHECK` constraint enforcing the equation today (SQLite CHECKs can't express the self-join), so the rule is convention enforced by the repository.

## Self-referential `parent` is `lazy="selectin"` with `join_depth=1`

`Organization.parent` is a self-referential relationship (the parent of an Org is another Org). The detail template dereferences `organization.parent.name` to render the parent's display name; under FastAPI's async sessions, an implicit lazy-load at template-render time fails with `MissingGreenlet`.

The fix is `lazy="selectin"` so the parent is loaded at the same session boundary as the target row. `join_depth=1` is required on a self-referential `selectin` — without it SQLAlchemy's cycle guard suppresses the eager-load and the strategy silently falls back to plain lazy-load (the exact failure mode that prompted this configuration). One hop is enough for the template; deeper ancestry is not used.

## Why this cluster, not flat siblings

`organizations/` matches the per-entity cluster grammar in [`../README.md`](../README.md) — every entity with at least one model file gets its own directory. The Program entity (PR 4 of the Org/Program roadmap, #537) is owned by Organization but lives in its own [`../programs/`](../programs/) cluster — same parent-cluster grammar applied recursively, not nested inside `organizations/`.
