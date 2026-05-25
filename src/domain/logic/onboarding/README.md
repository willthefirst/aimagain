# Onboarding logic cluster

Wizard state machine, service functions, and wire schemas for the `/welcome/*`
bespoke router (`src/domain/routes/welcome.py`).

## State machine

`state_machine.py:next_step(user, *, db)` is the single source of truth for
"where does this user go next?" Every wizard route that needs a redirect calls
it. The signal table:

| Signal | Source |
|---|---|
| `intent` | `user.onboarding_intent` |
| `has_clinician` | `user.providers` non-empty (selectin-loaded) |
| `clinician_verified` | onboarding clinician's latest `Verification.status == 'verified'` |
| `has_opening` | onboarding clinician owns ≥1 `OpeningDetail` — checked via `_has_opening()` |
| `has_reciprocity_profile` | clinician has non-empty specialties AND modality (T5+) |

### Truth table (current)

| intent | has_clinician | clinician_verified | has_opening | has_reciprocity_profile | next URL |
|---|---|---|---|---|---|
| any | False | — | — | — | `/welcome/verify` |
| any | True | False | — | — | `/welcome/verify` |
| `refer_now` | True | True | — | False | `/welcome/be-findable` |
| `refer_now` | True | True | — | True | `/openings` (terminal) |
| `have_openings` | True | True | False | — | `/welcome/first-opening` |
| `have_openings` | True | True | True | — | `/welcome/done` |
| `building_network` | True | True | False | — | `/welcome/minimal-profile` (T7) |
| `building_network` | True | True | True | — | `/welcome/done` (T7) |
| `invited` | True | True | False | — | `/welcome/minimal-profile` (T7) |
| `invited` | True | True | True | — | `/welcome/done` (T7) |

**Terminal rule**: Repeat visits to `/welcome/done` re-render the done page — the natural exit is the "Go to the board" CTA. No session flag is used (see `state_machine.py` comment).

`has_reciprocity_profile(clinician)` returns True when the clinician's
`primary_affiliation` has non-empty `specialties` AND at least one modality
(`in_person_sessions == "yes"` OR `virtual_sessions == "yes"`). AND not OR
because neither alone is sufficient to be findable. Implemented synchronously
— Provider loads Affiliations via `lazy="selectin"`.

The `building_network` flow also has a `GET /welcome/start-network` step (C1b) that
captures specialty selections into the session before routing through verify. It is
reached directly via the landing page link, not via `next_step()`.

## Session keys

`start_network_specialties` — set by `POST /welcome/start-network`, consumed and cleared
by `POST /welcome/minimal-profile`. Persists across the verify step so the user's
specialty selections survive the redirect chain.

### Onboarding clinician convention

The wizard always operates on the **most-recently-created `Provider`** owned by
the user: `onboarding_clinician(user) = max(user.providers, key=lambda p: p.created_at)`.
Every downstream ticket uses this helper — never inline the definition.

## Bespoke-shim pattern

Every wizard write is a function in `services.py` that:
1. Validates form data via a Pydantic schema in `schema.py`
2. Delegates to existing domain repo primitives / handlers
3. Owns the transaction (or delegates to the verification pipeline, which commits)
4. Returns the primary created/updated model

The route handler calls the service function, then redirects via `next_step()`.
There is no `return_to` primitive — wizard redirects are always determined by
the state machine.

## No `return_to` primitive

Wizard redirects are always state-machine-driven. There is no `?return_to=`
query-string pass-through. If a non-onboarding use case emerges that needs a
`return_to` primitive, design it then — don't add it speculatively here.
