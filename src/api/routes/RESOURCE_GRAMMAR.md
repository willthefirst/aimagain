# Resource grammar

The **prescriptive contract** for how every CRUD-shaped resource is exposed over HTTP. It governs URL shape, subresources, the optional publication lifecycle, and when each pattern applies. Read this **before** adding or modifying a resource type.

The grammar carries zero domain knowledge — domain meaning lives in the service layer. That split is what makes the surface scale: adding `/posts` or `/widgets` is following the rulebook, not redesigning the URL space.

The publication lifecycle (`draft | published | archived`) is **not** universal. Resources opt in when it has real domain meaning. Forcing it on sessions, API keys, audit rows, or webhooks creates ceremony without honest semantics.

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

- **`PATCH` is for ordinary, multi-field edits only.** It MUST NOT carry status transitions, role changes, password changes, or anything else with different rules — those go to subresources.
- **`DELETE`'s semantics are resource-defined.** Non-lifecycle resource: hard delete. Lifecycle-adopting resource: soft (transition to `archived`), with `DELETE /<r>/{id}/data` as the hard-delete escape hatch.
- **No `PUT` on the parent.** `PATCH` is the honest verb for partial edits.
- **All inputs MUST be validated by a Pydantic schema** (see `src/schemas/README.md`).

### PUT vs PATCH on subresources

- **`PUT /<r>/{id}/<sub>`** — idempotent set of a single value. Use when the subresource is one logical setting (a status, a role, a password, an email).
- **`PATCH /<r>/{id}/<sub>`** — partial update of a multi-field cluster. Use only when the subresource genuinely owns several fields edited together.
- **`POST /<r>/{id}/<event>`** — event-shaped transitions (emit a record, send mail) rather than idempotent sets.

Almost all subresources here are single-value sets and use `PUT`. The verb is part of the contract.

Server-managed fields (`id`, `created_at`, `updated_at`, plus any field whose authority belongs to the server) MUST be scrubbed from inbound payloads.

## Subresource toolkit

When something doesn't fit on the parent (different rules, audit, auth, or shape), it's a subresource. Four kinds — don't invent a fifth without updating this document.

### 1. state axes (including lifecycle)

When a resource has a meaningful state machine, model each axis as its own subresource:

```
PUT  /<resource>/{id}/<axis>         set the axis value
POST /<resource>/{id}/<event>        event-shaped transition (e.g. /publication, /archival)
```

The service layer enforces legal transitions and authorization. A resource may have zero, one, or several state-axis subresources — adopt only those with real domain meaning. Examples:

```
PUT /posts/{id}/status                draft | published | archived (publication lifecycle)
PUT /users/{id}/verification          pending | verified
PUT /api-keys/{id}/revocation         active | revoked
```

#### The publication lifecycle (opt-in)

The most common state axis is publication:

```
status: "draft" | "published" | "archived"
published_at: datetime | None
```

| State | Meaning |
| --- | --- |
| `draft` | Exists, not yet active. Excluded from default listings. |
| `published` | Active and visible per its visibility rules. |
| `archived` | Soft-deleted. Hidden by default; recoverable by admins. |

Adopting it is a package deal — see [Lifecycle disciplines](#lifecycle-disciplines).

### 2. field clusters with different auth

When a subset of fields has a different authorization rule, group them under a subresource:

```
PUT /users/{id}/role              admin-only
PUT /users/{id}/email             with verification flow
PUT /users/{id}/password          self-only, re-auth required
```

Single-value sets → `PUT`. A genuine multi-field cluster (e.g. a billing address edited together) → `PATCH`.

### 3. forms (HTML rendering)

HTML pages are subresources, not query parameters on the read endpoint:

```
GET /<resource>/form                   create form
GET /<resource>/{id}/form              edit page
GET /<resource>/{id}/<sub>/form        edit page for a subresource
```

A form page MAY host multiple `<form>` HTML tags posting to different action endpoints. **One `/form` per page, not per HTML form tag.** When a flow needs its own page (e.g. password change with re-auth), it gets its own subresource and `/form`.

**Every form-bearing resource MUST have a contract test pair** in [`tests/test_contract/`](../../../tests/test_contract/README.md). One consumer test (browser drives the form, asserts the request shape via Pact) and one provider test (running provider verified against the pact). Contract tests catch template ↔ route drift that no single colocated test can — adding them is part of the definition of done for any new HTML form.

### 4. revisions

When edits to a `published` resource must not be destructive (audit, review, autosave):

```
POST  /<resource>/{id}/revisions                       start a draft revision
PATCH /<resource>/{id}/revisions/{rev_id}              autosave
POST  /<resource>/{id}/revisions/{rev_id}/publication  apply revision to live
```

Only meaningful for lifecycle-adopting resources. Add lazily.

### Bonus: hard DELETE

```
DELETE /<resource>/{id}/data       hard delete (compliance / GDPR)
```

Only needed for lifecycle-adopting resources (where parent `DELETE` is soft). Always admin-only (or self for compliance).

## The decision rule

> **Does editing or operating on this thing have different rules — auth, audit, rate-limit, validation, side effects — than the rest of the resource?**
>
> - **Yes** → subresource. Pick a kind from the toolkit.
> - **No** → ordinary field. Edit via parent `PATCH`.

If unsure, default to subresource. Inlining is the harder mistake to undo.

## Disciplines

These MUST be handled in code. Not optional.

1. **Audit log on every mutation.** Every parent and subresource `PATCH` / `PUT` / `POST`-event MUST write an append-only row: `(actor, resource, action, before, after, at)`.
2. **Server-controlled fields are scrubbed** from inbound payloads before the service touches them.
3. **Verb consistency on subresources** per the [PUT vs PATCH rule](#put-vs-patch-on-subresources).
4. **One source of truth per axis.** A `status` enum and a redundant `is_active` boolean WILL drift. Make one derived from the other, or delete the redundancy.

### Lifecycle disciplines

Resources that adopt the publication lifecycle MUST also follow these:

1. **Default-filter at the query layer.** `GET /<resource>` defaults to `status=published`; other filters require explicit opt-in and permission. Every list/count/search/join MUST go through a shared visibility helper. One forgotten filter leaks drafts.
2. **Schema split for create/update vs. publish.** Drafts validate against a permissive schema (most fields optional); `draft → published` validates against a strict one. Two Pydantic classes; don't share.
3. **`POST` creates in `draft`.** Server-forced; the client cannot pick a different starting state.
4. **`DELETE /<r>/{id}` routes to the archived transition.** `DELETE /<r>/{id}/data` is the hard escape hatch.
5. **`published_at` is server-managed.** Add it to the scrub list.

## Worked example: `/users`

`/users` does **not** adopt the publication lifecycle — users don't honestly map to draft/published/archived. Instead it has two state axes: `verification` and `activation`.

### State axes

```
PUT /users/{id}/verification     pending | verified
PUT /users/{id}/activation       active | deactivated
```

Self-signup creates a user with `verification=pending, activation=active` and limited capability until verified. Admin deactivation sets `activation=deactivated`.

### Parent endpoints

```
POST   /users                     create                                        (admin or self-signup)
GET    /users                     list                                          (authed)
GET    /users/{id}                read                                          (authed; visibility rules)
PATCH  /users/{id}                edit ordinary profile fields                  (self or admin)
DELETE /users/{id}                hard delete                                   (admin or self)
```

`PATCH /users/{id}` MUST NOT accept `verification`, `activation`, `role`, `email`, `password`, `is_superuser`, or `id` — each is a subresource or server-managed.

### Subresources

| Subresource | Endpoints | Toolkit kind | Notes |
| --- | --- | --- | --- |
| `password` | `GET /users/{id}/password/form`, `PUT /users/{id}/password` | Field cluster | Self-only. Current-password re-auth, or one-time token. |
| `email` | `GET /users/{id}/email/form`, `PUT /users/{id}/email` | Field cluster | Triggers verification email; not changed until confirmed. |
| `role` | `PUT /users/{id}/role` | Field cluster | Admin-only. Audited. |
| `verification` | `PUT /users/{id}/verification` | State axis | Set by the email-verify token handler; not directly callable by clients. |
| `activation` | `PUT /users/{id}/activation` | State axis | Admin to deactivate/reactivate; self may set self → `deactivated`. |

### Form pages (HTML)

```
GET /users/form                       create form               (admin)
GET /users/{id}/form                  edit page (profile)       (self or admin)
GET /users/{id}/password/form         password-change page      (self only)
GET /users/{id}/email/form            email-change page         (self only)
```

`/me` is a convenience alias for `/users/{current_user.id}`. Sugar, not grammar.

## Checklist: adding a new resource

Stop at any step where the answer is "not needed yet" — subresources are added lazily.

1. **Decide if the publication lifecycle applies.** Real `draft | published | archived` semantics? Opt in (and accept the [lifecycle disciplines](#lifecycle-disciplines)). Otherwise — sessions, audit rows, API keys, users — don't bolt on a fake one.
2. **Identify other state axes.** Each is its own state-axis subresource.
3. **Identify field clusters.** Group by who-can-edit and what-rules-apply. Anything off the parent's rules → field-cluster subresource. Single value → `PUT`; multi-field → `PATCH`.
4. **Decide if revisions are needed.** Only meaningful for lifecycle resources where destructive edits are unacceptable. Default: edit-in-place.
5. **Wire the parent CRUD** per the grammar. Use the [adding a new domain entity](../../README.md#adding-a-new-domain-entity) cross-layer checklist.
6. **Wire each subresource.** One file under `src/api/routes/`; own schema, service method, authz, audit hook, colocated test.
7. **Wire the form pages** as needed. **Each `/form` gets a contract test pair** in `tests/test_contract/`.
8. **Verify the disciplines.** Universal disciplines on every mutation. If lifecycle-adopting, also: visibility filter, schema split, `POST` forces draft, `DELETE` routes to archived.

## Checklist: modifying an existing resource

1. **Apply the decision rule.** Different rules → subresource.
2. **Locate it on the grammar.** Which subresource kind? If none fit, propose a grammar-level change first.
3. **Confirm the URL and verb.** Single-value → `PUT`; multi-field → `PATCH`; event-shaped → `POST`.
4. **Confirm the disciplines.** Audit row? If lifecycle-adopting: publish-schema check or visibility filter touched?
5. **Implement across layers** per the [definition of done](../../../CLAUDE.md#definition-of-done).

## When the grammar doesn't fit

Don't deviate silently. Open this doc, propose the change at the grammar level, justify why no existing pattern fits. If accepted, the change applies retroactively as convention all resources converge on.

The grammar is allowed to evolve. It is not allowed to fork.
