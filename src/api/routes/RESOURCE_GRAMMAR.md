# Resource grammar

This document is the **prescriptive contract** for how every CRUD-shaped resource in this codebase is exposed over HTTP. It governs URL shape, lifecycle, subresources, and the rules for when to introduce one. Read this **before** adding a new resource type or modifying an existing one's surface area.

The grammar exists so that adding `/posts`, `/widgets`, or `/anything` after `/users` is a matter of *following the rulebook*, not redesigning the URL space each time.

## Why this exists

Every resource in this codebase MUST present the same URL grammar, the same lifecycle states, and the same toolkit for handling concerns that don't fit on the parent. The grammar carries zero domain knowledge — domain meaning lives in the service layer. This split is what makes the surface scale.

If you find yourself wanting to deviate, that's a signal to (a) introduce a subresource, or (b) raise the deviation as a grammar-level change in this document. Do not silently invent a new pattern in one resource; it will drift, and reviewers will not catch it.

## The grammar

Every resource MUST expose this exact URL shape. Nothing more on the parent, nothing less.

```
POST    /<resource>                  create
GET     /<resource>                  list (defaults to status=published)
GET     /<resource>?status=draft     list drafts (permissioned)
GET     /<resource>?status=archived  list archived (permissioned)

GET     /<resource>/{id}             read
PATCH   /<resource>/{id}             update *ordinary fields only*
DELETE  /<resource>/{id}             archive (soft-delete)
```

Rules:

- **`PATCH` is for ordinary field edits only.** It MUST NOT carry status transitions, role changes, password changes, or anything else with different rules. Those go to subresources (see toolkit below).
- **`DELETE` is soft.** It transitions the resource to `status="archived"`. Hard delete is a separate subresource (`DELETE /<resource>/{id}/data`).
- **`POST /<resource>` always creates in `draft` state.** Server forces this; the client cannot ask for a different starting state.
- **List endpoints default to `status=published`.** Filtering to other states requires both an explicit `?status=` and the appropriate permission.
- **All inputs MUST be validated by a Pydantic schema** (see `src/schemas/README.md`). Status transitions must validate against the *full* publish schema; field edits validate against a partial schema.

## State machine

Every resource carries the same three states:

```
status: "draft" | "published" | "archived"
published_at: datetime | None
```

The grammar is one-dimensional on purpose. If a resource needs an additional independent state axis (e.g. `verification`, `suspension`), that axis MUST be modeled as its own subresource (see "State axes" in the toolkit), not added to this enum.

| State | Generic meaning | Domain meaning is set per resource |
| --- | --- | --- |
| `draft` | Resource exists, not yet active. Excluded from default listings. | E.g. unverified user, unpublished post. |
| `published` | Resource is active and visible per its visibility rules. | E.g. live user account, public post. |
| `archived` | Resource is soft-deleted. Hidden by default; recoverable by admins. | E.g. banned user, retracted post. |

Server-managed fields (`published_at`, `created_at`, `updated_at`, `id`) MUST NOT be settable via any client-provided patch. The service layer scrubs them on inbound payloads.

## Subresource toolkit

When something does not fit on the parent (different rules, different audit, different auth, different shape), it becomes a subresource. There are five reusable kinds. Use these; do not invent a sixth without updating this document.

### 1. lifecycle transitions

For state changes that have side effects (emails, audit logs, validation gates), or for any axis beyond `status`:

```
PUT   /<resource>/{id}/<axis>        idempotent set of the axis value
# Or, when the transition is event-shaped (e.g. emits a record):
POST  /<resource>/{id}/<event>       e.g. /publication, /archival
```

The service layer enforces which transitions are legal and which caller is allowed to make them.

### 2. field clusters with different auth

When a subset of fields has a different authorization rule than the rest of the resource, group them under a subresource:

```
PATCH /users/{id}/role            admin-only
PATCH /users/{id}/email           with verification flow
PUT   /users/{id}/password        self-only, re-auth required
```

This keeps authorization uniform within a single endpoint. No per-field policy matrix in one handler.

### 3. independent state axes

When a resource has more than one orthogonal state (e.g. published vs. verified vs. suspended), each axis is its own subresource:

```
PUT /users/{id}/status            draft | published | archived
PUT /users/{id}/verification      pending | verified
PUT /users/{id}/suspension        none | suspended | banned
```

### 4. forms (HTML rendering)

HTML edit/create pages are subresources, not query parameters on the read endpoint. This keeps the resource URL representation-pure for non-HTML clients.

```
GET /<resource>/form                   create form
GET /<resource>/{id}/form              edit page
GET /<resource>/{id}/<sub>/form        edit page for a subresource
```

A form page MAY host multiple `<form>` HTML tags, each posting to its own action endpoint. **One `/form` per page, not one `/form` per HTML form tag.** When a flow deserves its own page (e.g. password change, with re-auth), it MUST be a separate subresource with its own `/form`.

### 5. revisions / drafts of edits

When edits to a `published` resource must not be destructive (audit, review, autosave), introduce revisions as a subresource:

```
POST  /<resource>/{id}/revisions                  start a draft revision
PATCH /<resource>/{id}/revisions/{rev_id}         autosave
POST  /<resource>/{id}/revisions/{rev_id}/publication   apply revision to live
```

Add lazily, only when the destructive-edit problem becomes real for that resource.

### Bonus: hard DELETE

```
DELETE /<resource>/{id}/data       hard delete (compliance / GDPR)
```

Always a separate URL from soft-delete. Always admin-only (or self for compliance requests).

## The decision rule

This is the load-bearing rule. Every reviewer should be able to recite it:

> **Does editing or operating on this thing have different rules — auth, audit, rate-limit, validation, side effects — than the rest of the resource?**
>
> - **Yes** → it is a subresource. Pick a kind from the toolkit.
> - **No** → it is an ordinary field. Edit via parent `PATCH`.

If you are unsure, default to subresource. Inlining a special case into the parent is the harder mistake to undo.

## Disciplines the grammar relies on

The grammar resolves most CRUD design questions, but it leaves a few that MUST be handled by code-level discipline. These are not optional.

1. **Default-filter at the query layer.** `GET /<resource>` defaulting to `status=published` is security-critical. Every list query, count query, search query, and join-back-to-resource MUST go through a shared visibility helper. One forgotten filter leaks drafts.
2. **Audit log on `PATCH`.** Every parent and subresource `PATCH`/`PUT` MUST write an append-only audit row: `(actor, resource, action, before, after, at)`. This is the floor; full revision history is a later upgrade.
3. **Server-controlled fields are scrubbed.** `id`, `published_at`, `created_at`, `updated_at`, plus any field whose authority belongs to the server, MUST be stripped from inbound payloads before the service touches them.
4. **Schema split for create/update vs. publish.** The schema validating `POST` and `PATCH` while a resource is `draft` is permissive (most fields optional). The schema validating a transition into `published` is strict (full required-fields check). These are two different Pydantic classes — don't try to share one.
5. **One source of truth per axis.** If a resource model has both a `status` field and a redundant boolean (e.g. legacy `is_active`), make one a derived check of the other or migrate off the redundancy. They WILL drift.

## Worked example: `/users`

The current `/users` surface is intentionally minimal. The grammar dictates the full target shape below. New endpoints land per the grammar; nothing is added off-grammar.

### State enum (per the grammar)

```
status: "draft" | "published" | "archived"
```

| State | Meaning for users |
| --- | --- |
| `draft` | Account exists; cannot authenticate. Used for unverified self-signups and admin-provisioned accounts before activation. |
| `published` | Active, can authenticate, appears in default listings. |
| `archived` | Deactivated. Cannot authenticate. Hidden from default listings. Recoverable by admin. |

### Parent endpoints

```
POST   /users                     create — server forces status=draft         (admin-only)
GET    /users                     list published                              (authed)
GET    /users?status=draft        list drafts (e.g. pending signups)          (admin-only)
GET    /users?status=archived     list archived                               (admin-only)

GET    /users/{id}                read                                        (authed; visibility rules apply)
PATCH  /users/{id}                edit ordinary profile fields                (self or admin)
DELETE /users/{id}                archive (soft-delete / deactivate)          (admin, or self for self-deletion)
```

`PATCH /users/{id}` MUST NOT accept `status`, `role`, `email`, `password`, `published_at`, `is_superuser`, or `id`. Each of those is either a subresource or server-managed.

### Subresources

| Subresource | Endpoints | Toolkit kind | Notes |
| --- | --- | --- | --- |
| `password` | `GET /users/{id}/password/form`, `PUT /users/{id}/password` | Field cluster (different auth) | Self-only. Requires current-password re-auth, or one-time token for set-after-provision. |
| `email` | `GET /users/{id}/email/form`, `PUT /users/{id}/email` | Field cluster (different flow) | Triggers verification email. Email is not actually changed until verification is confirmed. |
| `role` | `PATCH /users/{id}/role` | Field cluster (different auth) | Admin-only. Audited. |
| `status` | `PUT /users/{id}/status` | State axis | Admin-only for `published ↔ archived` (deactivate / reactivate). Self may transition self → `archived` (self-deletion). `draft → published` happens via the verification token flow, not direct PUT. |
| `verification` | `PUT /users/{id}/verification` | State axis | Set by the email-verify token handler. Not directly callable by clients. |
| `data` | `DELETE /users/{id}/data` | Hard delete | GDPR-style erasure. Admin or self. |

### Form pages (HTML)

```
GET /users/form                       create form               (admin-only)
GET /users/{id}/form                  edit page (profile)       (self or admin)
GET /users/{id}/password/form         password-change page      (self only)
GET /users/{id}/email/form            email-change page         (self only)
```

`/me` remains as a convenience alias that resolves to `/users/{current_user.id}`. It is not part of the grammar; it is sugar.

### Where the existing app sits today

| Capability | Status | Future location per grammar |
| --- | --- | --- |
| `GET /users` (list) | Implemented | Stays as-is; gain `?status=` filtering. |
| `POST /auth/register` (self-signup) | Implemented via FastAPI-Users | Conceptually equivalent to "POST /users + draft → token-gated transition to published". The `/auth/register` URL is preserved as the public-facing signup entrypoint; under the hood it MUST conform to the same lifecycle. |
| `/me` profile | Implemented | Becomes an alias for `/users/{self_id}`. |
| Admin deactivate user | Not implemented | `PUT /users/{id}/status {status: "archived"}` (or `DELETE /users/{id}`, which routes to the same transition). |
| Edit user profile fields | Not implemented | `GET /users/{id}/form` + `PATCH /users/{id}`. |
| Change password | Partially (via FastAPI-Users) | `GET /users/{id}/password/form` + `PUT /users/{id}/password`. |

## Checklist: adding a new resource

When you introduce a new resource type (e.g. `/posts`), follow this in order. Stop at any step where the answer is "not needed yet" — subresources are added lazily.

1. **Identify the state axes.** What independent things change about this resource over its life? If the answer is "just the lifecycle," you have one axis (`status`) and you're done. If there are more (e.g. moderation status, scheduled-publish time), each is its own state-axis subresource.
2. **Identify the field clusters.** Group fields by who-can-edit-them and what-rules-apply. Fields that share a rule with the rest of the resource stay on the parent. Anything else is a field-cluster subresource.
3. **Identify any non-default deletion semantics.** If the resource needs hard delete (GDPR, content takedown), plan for `DELETE /<resource>/{id}/data` from day one.
4. **Decide if revisions are needed yet.** For most resources, edit-in-place is fine for v1. If destructive edits are unacceptable (regulated content, collaborative editing), plan revisions.
5. **Wire the parent CRUD.** Implement `POST` / `GET` (list) / `GET` (read) / `PATCH` / `DELETE` per the grammar. Use the [`adding a new domain entity`](../../README.md#adding-a-new-domain-entity) cross-layer checklist for the model/migration/schema/repo/service/route stack.
6. **Wire each identified subresource.** One file per subresource under `src/api/routes/`. Each has its own schema, service method, authz rule, audit hook, and colocated test.
7. **Wire the form pages.** `GET /<resource>/form`, `GET /<resource>/{id}/form`, plus a `/form` for any subresource that warrants its own page.
8. **Verify the disciplines.** Confirm: default visibility filter is in place; audit log writes on every mutation; server-controlled fields are scrubbed; create/update vs. publish schemas are split.

## Checklist: modifying an existing resource

When you add a capability to an existing resource (e.g. "admins can deactivate users"):

1. **Apply the decision rule.** Is this an ordinary field edit or does it have different rules? If different rules → subresource.
2. **Locate it on the grammar.** Which subresource kind is it (transition, field cluster, state axis, form, revision, hard delete)? If none fit, the change MAY warrant a grammar-level update — raise it as a doc change first.
3. **Confirm the URL.** Match the grammar exactly. Don't invent a verb.
4. **Confirm the disciplines.** Does the change need an audit row? Does it need a publish-schema check? Does it touch the visibility filter?
5. **Implement across layers.** Model (if a new field is needed) → migration → schema → repository method → service method (with authz) → route → form template (if HTML) → colocated test → README updates per the [definition of done](../../../CLAUDE.md#definition-of-done).

## When the grammar doesn't fit

If a real requirement cannot be expressed in the grammar above, the answer is **not** to deviate silently in one resource. The answer is:

1. Open this document and propose the change at the grammar level.
2. Justify it: which existing pattern is insufficient, and why no subresource shape covers the case.
3. If accepted, the change applies retroactively as a convention all resources should converge on.

The grammar is allowed to evolve. It is not allowed to fork.
