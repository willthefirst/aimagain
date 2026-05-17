# Organizations cluster

First-class directory entity for clinics, group practices, health systems, and solo-practice shells. PR 1 of the Org/Program roadmap — this cluster ships standalone; no relationships from `Organization` to `Provider` yet. The Provider migration onto `org_id` lands in PR 2.

The parent layer's conventions (BaseModel inheritance, FK CASCADE, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to organizations.

## Files

- `organization.py` — `Organization`. Hierarchy via a nullable self-FK `parent_org_id` and a denormalized non-nullable `root_org_id`. Tied to a `User` via non-unique `owner_id` FK + CASCADE (mirrors `Provider.owner_id` — one user may own many orgs). Enum column `type` CHECKs against `ORGANIZATION_TYPES` from [`../enums.py`](../enums.py).

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

## Why this cluster, not flat siblings

`organizations/` matches the per-entity cluster grammar in [`../README.md`](../README.md) — every entity with at least one model file gets its own directory. PR 4 of the Org/Program roadmap (Program entity, owned by Organization) will add `program.py` next to `organization.py` in this same cluster, sharing the `ORGANIZATION_TYPES` enum and the parent/root denormalization pattern.
