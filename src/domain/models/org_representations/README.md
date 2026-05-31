# Org representations cluster

`OrgRepresentation` carries **Claim B** in the two-claim verification model: the User-↔-Organization link with authority semantics.

## Why this isn't `Affiliation`

Both rows have a FK to `organizations.id`. They are not the same:

| | `Affiliation` (`clinician_affiliations` someday) | `OrgRepresentation` |
|---|---|---|
| Subject | `Clinician` | `User` |
| Carries | practice attrs (location, insurance, modality, sliding-scale, cost) | authority (role, authority_method, authority_status, approver) |
| Answers | "Where does this clinician practice?" | "Who is authorized to speak for this org?" |
| Lifecycle | created when a clinician joins a practice; deleted when they leave | created when a user proves authority; **archived** on revoke (`archived_at`), not deleted |

A clinician can be affiliated with an org without being authorized to speak for it (group-practice clinicians who aren't admins). A user can represent an org without being one of its clinicians (program coordinator with no Type-1 NPI).

## Authority paths (handoff §6)

- `authorized_official` — NPPES Authorized-Official name-match against the requesting user's verified `Clinician` name. Auto, covers most solos.
- `domain_email` — verified email at the org's domain. **v1 stub**: handler returns "not yet enabled" until an `OrganizationDomain` table + email-at-domain verification flow lands.
- `rep_approval` — an existing verified rep (or admin) approves the new rep via the `authority` state axis. Sets `approved_by` to the approver's user id.
- `admin_review` — fallback for orgs where neither auto-path applies.

The org's Type-2 NPI is verified **once per Organization** (`Organization.org_verified`). Authority is per-(user, org) and lives here.

## Revocation

Setting `authority_status = 'rejected'` or `archived_at = NOW()` pauses any org-attributed posts authored under this representation but preserves them — `archive, don't delete` per §10.8.
