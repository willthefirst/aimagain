# Programs cluster

The SQLAlchemy model for the `programs` table. A :class:`Program` is a treatment offering owned by an :class:`Organization` — distinct from :class:`Provider` (a clinician). PR 4 of the Org/Program roadmap (#537).

The model file's own docstring documents the column-level grammar (ownership, `state_preference` independence from the parent Org, no insurance fields). This README captures only the cross-file ties that aren't visible from inside `program.py`:

- **Reverse FKs** — :class:`Program` is referenced from:
  - A Provider's Org link lives on :class:`Affiliation.org_id`, not on the Program — Providers attach to Orgs (via their affiliation), not Programs (the Program is the intake door; the Provider does the clinical work).
  - :class:`IntakeDetail.program_id` (#541) — posts of kind `intake` announce a Program's intake openings. `program.intake_details` back-populates the relationship. Deleting a Program cascades through to its intake posts (a post about a deleted Program is stale by construction).

- **Form / authz wiring** — Program edits go through the framework's factory-built `mount_entity`; the `payload_authz_path` declared on `PROGRAM_ENTITY` enforces "the user may only attach a Program to an Org they own" (#537). The intake post create flow has its own `payload_authz` check on `POST_ENTITY` (#541) enforcing "the user may only post Program-availability for a Program they own" — same shape, different entity boundary.

- **Repository hook** — :class:`ProgramRepository.list_for_user` (#541) returns the requesting user's owned Programs, newest first; consumed by `User.programs` (eager `selectin` reverse FK) which the intake create form reads to populate the Program-picker dropdown.
