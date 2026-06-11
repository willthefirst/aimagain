# Programs cluster

The SQLAlchemy model for the `programs` table. A :class:`Program` is a treatment offering owned by an :class:`Organization` — distinct from :class:`Clinician`. PR 4 of the Org/Program roadmap (#537).

The model file's own docstring documents the column-level grammar (ownership, `state_preference` independence from the parent Org, no insurance fields). This README captures only the cross-file ties that aren't visible from inside `program.py`:

- **Reverse FKs** — :class:`Program` is referenced from:
  - A Clinician's Org link lives on :class:`ClinicianAffiliation.org_id`, not on the Program — Clinicians attach to Orgs (via their affiliation), not Programs (the Program is the intake door; the Clinician does the clinical work).
  - :class:`IntakeDetail.program_id` (#541) — posts of kind `intake` announce a Program's intake openings. `program.intake_details` back-populates the relationship. Deleting a Program cascades through to its intake posts (a post about a deleted Program is stale by construction).

- **Form / authz wiring** — Program edits go through the framework's factory-built `mount_entity`; the `payload_authz_path` declared on `PROGRAM_ENTITY` enforces "the user may only attach a Program to an Org they own" (#537). The intake post create flow has its own `payload_authz` check on `POST_ENTITY` (#541) enforcing "the user may only post Program-availability for a Program they own" — same shape, different entity boundary.

- **Repository hook** — :class:`ProgramRepository.list_for_user` (#541) returns the requesting user's owned Programs, newest first; consumed by `User.programs` (eager `selectin` reverse FK) which the intake create form reads to populate the Program-picker dropdown.

## Steady-state profile (#1358 PR-f, in progress)

The columns `services` / `settings` / `modalities` / `age_groups` / `genders` / `languages` / `website` / `referral_instructions` / `currently_accepting_new_patients` are the Program's **steady-state offering profile** — the program-side mirror of [`ClinicianAffiliation`'s steady-state profile](../clinician_affiliations/README.md#steady-state-profile-1358-pr-f-in-progress). The same field set, the same three-sub-PR sequence, the same "events go on Post, steady state goes here" model. The IntakeDetail → Program move is for the program-intake half; the OpeningDetail → ClinicianAffiliation move is the clinician-opening half. See the affiliation README for the full rationale.

Note that `languages` belongs on the Program directly (not on a person) — a Program is the offering, and which languages it covers is an attribute of the offering itself. `currently_accepting_new_patients` is distinct from the existing `accepting_referrals` flag: `accepting_referrals` is the operator's standing posture ("we generally take referrals"), while `currently_accepting_new_patients` is the cached "we have an active IntakeDetail right now" signal toggled by the announcement lifecycle in sub-PR 2/3.
