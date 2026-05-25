# User model

The `User` table extends fastapi-users' `SQLAlchemyBaseUserTable` with
Bedlam-Connect-specific columns. The base class owns `id`, `email`,
`hashed_password`, `is_active`, `is_superuser`, `is_verified`.

## Additional columns

| Column | Type | Nullable | Constraint | Notes |
| --- | --- | --- | --- | --- |
| `username` | `TEXT UNIQUE NOT NULL` | No | — | Auto-assigned from email on registration; editable via PATCH. |
| `onboarding_intent` | `TEXT` | Yes | `ck_users_onboarding_intent` — values in `ONBOARDING_INTENTS` | Why the user joined. See below. |

## `onboarding_intent` lifecycle

`onboarding_intent` captures why the user joined Bedlam Connect. It drives
the onboarding wizard (T2+). The value is nullable: users who joined before
the field existed, or who skipped the landing-page picker, have `NULL`.

The field follows a two-leg lifecycle:

1. **Pre-auth (anonymous visitor):** the landing page renders 4 intent
   cards. Clicking one POSTs to `POST /onboarding-intent-pending`, which
   stores the value in the Starlette session cookie and redirects to
   `/auth/register`.

2. **On registration:** `UserManager.on_after_register` in `auth_config.py`
   reads `request.session["onboarding_intent"]`, validates it against
   `ONBOARDING_INTENTS`, writes it to the new user row via
   `user_db.update(user, {"onboarding_intent": ...})`, then clears the
   session key.

**After registration**, the field is updated exclusively via
`PUT /users/me/onboarding-intent` (field-cluster subresource, self-only,
writes an `update_user_onboarding_intent` audit row). It is intentionally
absent from `UserUpdate` so ordinary `PATCH /users/{id}` cannot touch it.

Valid values are defined in `src/domain/models/enums.ONBOARDING_INTENTS` —
that tuple is the single source of truth for the CHECK constraint, the
Pydantic `Literal`, the Alembic migration, and the landing-page card set.
