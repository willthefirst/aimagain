"""Persona registry — single source of truth for the dev-login personas.

A persona is one of the auth-state fixtures the rest of the app
branches on. Each ``Persona`` carries everything the three downstream
consumers need:

  - ``scripts/dev/seed/overrides/users.py`` — to build the User row
    with the right ``is_verified`` / ``is_superuser``.
  - ``scripts/dev/seed/overrides/clinicians.py`` — to optionally
    anchor a Clinician owned by this persona with the right
    ``clinician_verified`` state.
  - ``scripts/dev/seed/overrides/posts.py`` — to exclude personas from
    the generic post-owner round-robin (post ownership has to reflect
    each kind's capability gate) and to anchor authored posts for the
    persona that holds the publishing capability.
  - ``src/domain/routes/dev/dev_auth.py`` — to surface the persona in the
    quick-sign-in dropdown with a human-readable label.

If a persona is renamed or a new one is added, this is the only file
that needs to change. The three consumers iterate ``PERSONAS`` and
read the fields they care about — no cross-file string-matching, no
re-export constants.

Lives under ``src/`` (and not ``scripts/``) because seed code is
allowed to import from ``src``, but ``src`` never imports from
``scripts`` — that's the direction the dependency graph runs.

The capability predicates in ``src/domain/logic/capabilities.py`` are
``any(...)`` over the owned set, so the persona's anchor clinician
must be the *only* Clinician the user owns — otherwise the
round-robin rotation in ``scripts/dev/seed/overrides/clinicians.py``
could assign a clinician whose state contradicts the persona. The
seed therefore excludes persona users from the generic round-robin
owner pool.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Persona:
    """One auth-state fixture.

    ``clinician_verified`` is tri-valued: ``True`` / ``False`` anchor a
    Clinician owned by this persona with the named verification state;
    ``None`` means "don't anchor a Clinician" (e.g. the
    ``email-unverified`` persona — no clinician needed, since
    ``email_verified(user)`` short-circuits False before any
    clinician-side state is consulted).
    """

    email: str
    username: str
    label: str
    is_verified: bool
    clinician_verified: bool | None


PERSONAS: tuple[Persona, ...] = (
    Persona(
        email="unverified@example.com",
        username="unverified",
        label="persona: email unverified",
        is_verified=False,
        clinician_verified=None,
    ),
    Persona(
        email="clinician-pending@example.com",
        username="clinician-pending",
        label="persona: email verified, clinician unverified",
        is_verified=True,
        clinician_verified=False,
    ),
    Persona(
        email="clinician-verified@example.com",
        username="clinician-verified",
        label="persona: email verified, clinician verified",
        is_verified=True,
        clinician_verified=True,
    ),
)
