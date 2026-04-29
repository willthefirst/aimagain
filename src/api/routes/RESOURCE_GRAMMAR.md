# Resource grammar

This document is the **prescriptive contract** for how every CRUD-shaped resource in this codebase is exposed over HTTP. It governs URL shape, subresources, the optional lifecycle pattern, and the rules for when to introduce one. Read this **before** adding a new resource type or modifying an existing one's surface area.

The grammar exists so that adding `/posts`, `/widgets`, or `/anything` after `/users` is a matter of *following the rulebook*, not redesigning the URL space each time.

## Why this exists

Every resource in this codebase MUST present the same URL grammar and use the same toolkit for concerns that don't fit on the parent. The grammar carries zero domain knowledge — domain meaning lives in the service layer. This split is what makes the surface scale.

Lifecycle (the `draft | published | archived` state machine) is **not** universal — it's a toolkit pattern resources opt into when it actually applies. Forcing it on every resource creates ceremony where there's no domain meaning (sessions, API keys, audit rows, webhooks, etc. have no honest mapping to publication state).

If you find yourself wanting to deviate, that's a signal to (a) introduce a subresource, or (b) raise the deviation as a grammar-level change in this document. Do not silently invent a new pattern in one resource; it will drift, and reviewers will not catch it.

## The grammar

Every resource MUST expose this exact URL shape on the parent. Nothing more, nothing less.

```
POST    /<resource>                  create
GET     /<resource>                  list
GET     /<resource>/{id}             read
PATCH   /<resource>/{id}             update *ordinary fields only*
DELETE  /<resource>/{id}             delete
```

Rules:

- **`PATCH` is for ordinary, multi-field edits only.** It MUST NOT carry status transitions, role changes, password changes, or anything else with different rules. Those go to subresources (see toolkit below).
- **`DELETE`'s semantics are resource-defined.** For a non-lifecycle resource, `DELETE /<r>/{id}` is hard delete. For a resource that adopts the [publication lifecycle](#the-publication-lifecycle-opt-in), `DELETE /<r>/{id}` is soft (transition to `archived`), and the hard-delete escape hatch is `DELETE /<r>/{id}/data`.
- **No `PUT` on the parent.** Full-replace semantics rarely match what clients want; `PATCH` is the honest verb for partial edits.
- **All inputs MUST be validated by a Pydantic schema** (see `src/schemas/README.md`).

### PUT vs PATCH on subresources

Every subresource MUST pick exactly one verb and use it consistently:

- **`PUT /<r>/{id}/<sub>`** — idempotent set of a single value or full replace. Use this when the subresource is one logical setting (a status, a role, a password, an email). Replays MUST be safe.
- **`PATCH /<r>/{id}/<sub>`** — partial update of a multi-field cluster. Use this only when the subresource genuinely owns several fields edited together.
- **`POST /<r>/{id}/<event>`** — for transitions that are event-shaped (emit a record, send a mail) rather than idempotent sets.

In practice, almost all subresources in this codebase are single-value sets and use `PUT`. `PATCH` shows up on the parent and on the rare multi-field cluster. Reviewers should reject the wrong choice — the verb is part of the contract.

Server-managed fields (`created_at`, `updated_at`, `id`, plus any field whose authority belongs to the server) MUST NOT be settable via any client-provided patch. The service layer scrubs them on inbound payloads.

## Subresource toolkit

When something does not fit on the parent (different rules, different audit, different auth, different shape), it becomes a subresource. There are four reusable kinds. Use these; do not invent a fifth without updating this document.

### 1. state axes (including lifecycle)

When a resource has a meaningful state machine, model each axis as its own subresource:

```
PUT  /<resource>/{id}/<axis>         idempotent set of the axis value
POST /<resource>/{id}/<event>        when the transition is event-shaped (e.g. /publication, /archival)
```

The service layer enforces which transitions are legal and which caller is allowed to make them. A resource may have zero, one, or several state-axis subresources — adopt only those with real domain meaning. Examples:

```
PUT /users/{id}/status            draft | published | archived (the publication lifecycle)
PUT /users/{id}/verification      pending | verified
PUT /users/{id}/suspension        none | suspended | banned
```

#### The publication lifecycle (opt-in)

The most common state axis is publication. Resources that adopt it use this exact axis:

```
status: "draft" | "published" | "archived"
published_at: datetime | None
```

| State | Generic meaning | Domain meaning is set per resource |
| --- | --- | --- |
| `draft` | Resource exists, not yet active. Excluded from default listings. | E.g. unverified user, unpublished post. |
| `published` | Resource is active and visible per its visibility rules. | E.g. live user account, public post. |
| `archived` | Resource is soft-deleted. Hidden by default; recoverable by admins. | E.g. banned user, retracted post. |

Adopting the publication lifecycle is a package deal — the resource MUST also follow the disciplines in [Disciplines lifecycle resources additionally rely on](#disciplines-lifecycle-resources-additionally-rely-on): default-filter visibility on lists, draft-vs.-publish schema split, server-forced `draft` on `POST`, and `DELETE /<r>/{id}` routing to the archived transition.

Resources without a meaningful publication lifecycle simply don't adopt it. They may still have other state axes (e.g. an `ApiKey` with `PUT /api-keys/{id}/revocation`), or none at all.

### 2. field clusters with different auth

When a subset of fields has a different authorization rule than the rest of the resource, group them under a subresource:

```
PUT /users/{id}/role              admin-only
PUT /users/{id}/email             with verification flow
PUT /users/{id}/password          self-only, re-auth required
```

Each example above is a single-value set, so all use `PUT`. A multi-field cluster (e.g. a billing-address block edited together) would be `PATCH`.

This keeps authorization uniform within a single endpoint. No per-field policy matrix in one handler.

### 3. forms (HTML rendering)

HTML edit/create pages are subresources, not query parameters on the read endpoint. This keeps the resource URL representation-pure for non-HTML clients.

```
GET /<resource>/form                   create form
GET /<resource>/{id}/form              edit page
GET /<resource>/{id}/<sub>/form        edit page for a subresource
```

A form page MAY host multiple `<form>` HTML tags, each posting to its own action endpoint. **One `/form` per page, not one `/form` per HTML form tag.** When a flow deserves its own page (e.g. password change, with re-auth), it MUST be a separate subresource with its own `/form`.

### 4. revisions / drafts of edits

When edits to a `published` resource must not be destructive (audit, review, autosave), introduce revisions as a subresource:

```
POST  /<resource>/{id}/revisions                  start a draft revision
PATCH /<resource>/{id}/revisions/{rev_id}         autosave
POST  /<resource>/{id}/revisions/{rev_id}/publication   apply revision to live
```

Only meaningful for resources that adopt the publication lifecycle. Add lazily, only when the destructive-edit problem becomes real for that resource.

### Bonus: hard DELETE

```
DELETE /<resource>/{id}/data       hard delete (compliance / GDPR)
```

Only needed for resources that adopt the publication lifecycle (so `DELETE /<r>/{id}` is soft and a separate hard-delete URL is required). For non-lifecycle resources, the parent `DELETE` is already hard and a separate `/data` URL is redundant.

Always admin-only (or self for compliance requests).

## The decision rule

This is the load-bearing rule. Every reviewer should be able to recite it:

> **Does editing or operating on this thing have different rules — auth, audit, rate-limit, validation, side effects — than the rest of the resource?**
>
> - **Yes** → it is a subresource. Pick a kind from the toolkit.
> - **No** → it is an ordinary field. Edit via parent `PATCH`.

If you are unsure, default to subresource. Inlining a special case into the parent is the harder mistake to undo.

## Disciplines the grammar relies on

The grammar resolves most CRUD design questions, but it leaves a few that MUST be handled by code-level discipline. These are not optional.

1. **Audit log on every mutation.** Every parent and subresource `PATCH` / `PUT` / `POST`-event MUST write an append-only audit row: `(actor, resource, action, before, after, at)`. This is the floor; full revision history is a later upgrade.
2. **Server-controlled fields are scrubbed.** `id`, `created_at`, `updated_at`, plus any field whose authority belongs to the server, MUST be stripped from inbound payloads before the service touches them.
3. **Verb consistency on subresources.** PUT vs PATCH per the [rule above](#put-vs-patch-on-subresources). Reviewers should reject the wrong choice.
4. **One source of truth per axis.** If a resource model has both a state field and a redundant boolean (e.g. a `status` enum and a legacy `is_active`), make one a derived check of the other or migrate off the redundancy. They WILL drift.

### Disciplines lifecycle resources additionally rely on

Resources that adopt the [publication lifecycle](#the-publication-lifecycle-opt-in) MUST also follow these disciplines. They are not optional for opt-in resources, and they don't apply to resources that don't adopt the lifecycle.

1. **Default-filter at the query layer.** `GET /<resource>` defaults to `status=published`; `?status=draft` and `?status=archived` require explicit opt-in and the appropriate permission. Every list query, count query, search query, and join-back-to-resource MUST go through a shared visibility helper. One forgotten filter leaks drafts.
2. **Schema split for create/update vs. publish.** The schema validating `POST` and `PATCH` while a resource is `draft` is permissive (most fields optional). The schema validating a transition into `published` is strict (full required-fields check). These are two different Pydantic classes — don't try to share one.
3. **`POST` creates in `draft`.** Server forces this; the client cannot ask for a different starting state.
4. **`DELETE /<r>/{id}` routes to the archived transition.** And `DELETE /<r>/{id}/data` is the hard-delete escape hatch.
5. **`published_at` is server-managed.** Add it to the scrub list.

## Worked example: `/users`

`/users` **opts into** the publication lifecycle (draft = unverified, archived = deactivated) plus an additional `verification` axis. The current surface is intentionally minimal; the grammar dictates the full target shape below. New endpoints land per the grammar; nothing is added off-grammar.

### Lifecycle adoption

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
| `role` | `PUT /users/{id}/role` | Field cluster (different auth) | Admin-only. Audited. Single-value set, so PUT. |
| `status` | `PUT /users/{id}/status` | State axis (publication lifecycle) | Admin-only for `published ↔ archived` (deactivate / reactivate). Self may transition self → `archived` (self-deletion). `draft → published` happens via the verification token flow, not direct PUT. |
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

1. **Decide if the publication lifecycle applies.** Does this resource genuinely have draft / published / archived states with real domain meaning? If yes, opt in (and accept the [extra disciplines](#disciplines-lifecycle-resources-additionally-rely-on)). If no — sessions, audit rows, API keys, ephemeral records — don't bolt on a fake one. `DELETE /<r>/{id}` is then a hard delete and you're done with deletion semantics.
2. **Identify any other state axes.** What independent things change about this resource over its life beyond the lifecycle? Each axis (e.g. moderation, suspension, scheduled-publish) is its own state-axis subresource.
3. **Identify the field clusters.** Group fields by who-can-edit-them and what-rules-apply. Fields that share a rule with the rest of the resource stay on the parent. Anything else is a field-cluster subresource — single value → `PUT`, multi-field → `PATCH`.
4. **Identify any non-default deletion semantics.** Lifecycle resources get `DELETE /<r>/{id}/data` for hard delete. Non-lifecycle resources only need a custom deletion subresource if there's a flow beyond the parent `DELETE`.
5. **Decide if revisions are needed yet.** Only meaningful for lifecycle resources where destructive edits to a `published` value are unacceptable. For most resources, edit-in-place is fine for v1.
6. **Wire the parent CRUD.** Implement `POST` / `GET` (list) / `GET` (read) / `PATCH` / `DELETE` per the grammar. Use the [`adding a new domain entity`](../../README.md#adding-a-new-domain-entity) cross-layer checklist for the model/migration/schema/repo/service/route stack.
7. **Wire each identified subresource.** One file per subresource under `src/api/routes/`. Each has its own schema, service method, authz rule, audit hook, and colocated test. Verb per the [PUT vs PATCH rule](#put-vs-patch-on-subresources).
8. **Wire the form pages.** `GET /<resource>/form`, `GET /<resource>/{id}/form`, plus a `/form` for any subresource that warrants its own page.
9. **Verify the disciplines.** Confirm: audit log writes on every mutation; server-controlled fields are scrubbed; subresource verbs are consistent. If lifecycle-adopting: default visibility filter is in place; create/update vs. publish schemas are split; `POST` forces draft; `DELETE` routes to archived.

## Checklist: modifying an existing resource

When you add a capability to an existing resource (e.g. "admins can deactivate users"):

1. **Apply the decision rule.** Is this an ordinary field edit or does it have different rules? If different rules → subresource.
2. **Locate it on the grammar.** Which subresource kind is it (state axis, field cluster, form, revision, hard delete)? If none fit, the change MAY warrant a grammar-level update — raise it as a doc change first.
3. **Confirm the URL and verb.** Match the grammar exactly. Don't invent a verb. Single-value subresource → `PUT`; multi-field cluster → `PATCH`; event-shaped → `POST`.
4. **Confirm the disciplines.** Does the change need an audit row? If the resource is lifecycle-adopting, does it need a publish-schema check or touch the visibility filter?
5. **Implement across layers.** Model (if a new field is needed) → migration → schema → repository method → service method (with authz) → route → form template (if HTML) → colocated test → README updates per the [definition of done](../../../CLAUDE.md#definition-of-done).

## When the grammar doesn't fit

If a real requirement cannot be expressed in the grammar above, the answer is **not** to deviate silently in one resource. The answer is:

1. Open this document and propose the change at the grammar level.
2. Justify it: which existing pattern is insufficient, and why no subresource shape covers the case.
3. If accepted, the change applies retroactively as a convention all resources should converge on.

The grammar is allowed to evolve. It is not allowed to fork.
