# Programs cluster

The SQLAlchemy model for the `programs` table. A :class:`Program` is a treatment offering owned by an :class:`Organization` — distinct from :class:`Clinician`. PR 4 of the Org/Program roadmap (#537).

The model file's own docstring documents the column-level grammar (ownership, `state_preference` independence from the parent Org, no insurance fields). This README captures only the cross-file ties that aren't visible from inside `program.py`:

- **Reverse FKs** — :class:`Program` is referenced from:
  - A Clinician's Org link lives on :class:`ClinicianAffiliation.org_id`, not on the Program — Clinicians attach to Orgs (via their affiliation), not Programs (the Program is the intake door; the Clinician does the clinical work).
  - :class:`IntakeDetail.program_id` (#541) — posts of kind `intake` announce a Program's intake openings. `program.intake_details` back-populates the relationship. Deleting a Program cascades through to its intake posts (a post about a deleted Program is stale by construction).

- **Form / authz wiring** — Program edits go through the framework's factory-built `mount_entity`; the `payload_authz_path` declared on `PROGRAM_ENTITY` enforces "the user may only attach a Program to an Org they own" (#537). The intake post create flow has its own `payload_authz` check on `POST_ENTITY` (#541) enforcing "the user may only post Program-availability for a Program they own" — same shape, different entity boundary.

- **Repository hook** — :class:`ProgramRepository.list_for_user` (#541) returns the requesting user's owned Programs, newest first; consumed by `User.programs` (eager `selectin` reverse FK) which the intake create form reads to populate the Program-picker dropdown.

## Steady-state profile (#1358 PR-f)

The columns `services` / `settings` / `modalities` / `age_groups` / `genders` / `languages` / `website` / `referral_instructions` / `currently_accepting_new_patients` are the Program's **steady-state offering profile** — the program-side home for the intake post's profile, under the "events go on Post, steady state goes here" model from #1358. Note the clinician side has since diverged: the per-announcement dimensions (services / session format / cohort / cost) moved *onto* the opening post, so `ClinicianAffiliation` no longer mirrors this Program field set — it now carries only steady-state *context* (location + insurance + how-to-refer). See [`../clinician_affiliations/README.md`](../clinician_affiliations/README.md). The program-intake side still follows the original split (profile on Program); a later PR may align it with the opening's self-describing shape.

Sub-PR 3 (drop the detail-row columns) has landed. The view layer (`src/domain/logic/posts/view.py`) reads steady-state fields exclusively from this Program row when an intake announcement is rendered; there is no fallback to a per-announcement column because none exists. `IntakeDetail` is now thin — see [`../posts/README.md`](../posts/README.md).

The Program edit/new forms (`src/domain/templates/programs/_form_new_fragment.html` and `form_edit.html`) collect these fields directly; the detail page (`detail.html`) renders each as a facts row. The wire schemas (`src/domain/logic/programs/schema.py`) accept all of them on `ProgramCreate` / `ProgramUpdate` and surface them on `ProgramRead`. Multi-select fields use the same `list[Literal[*TUPLE]] + scalar_to_list` shape as the post-side `services` / `modalities` aliases — see `src/domain/logic/posts/schema.py`.

Note that `languages` belongs on the Program directly (not on a person) — a Program is the offering, and which languages it covers is an attribute of the offering itself. `currently_accepting_new_patients` is distinct from the existing `accepting_referrals` flag: `accepting_referrals` is the operator's standing posture ("we generally take referrals"), while `currently_accepting_new_patients` is the cached "we have an active IntakeDetail right now" signal toggled by the announcement lifecycle.
