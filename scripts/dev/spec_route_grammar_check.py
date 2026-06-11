#!/usr/bin/env python3
"""Enforce the canonical resource grammar at the spec level.

`RESOURCE_GRAMMAR.md` lays out the URL shape every resource must
follow:

    /<collection>          list  (with "Create" in toolbar)
    /<collection>/form     create form
    /<collection>/{id}     detail  (optional per resource)
    /<collection>/{id}/form  edit form  (with Delete in actions)

The grammar shape is enforced via the `RouteSet` flags every
`EntitySpec` declares. A spec that mutates rows but doesn't declare
the corresponding form/list pages drifts off-grammar — users land on
inline-create / inline-delete affordances baked into the list page,
which then no longer satisfies "a GET is either a read view or a
form."

This check walks every registered spec (and its owned-subentity
children) and rejects:

  - `create=True` without `form_new=True`
  - `update=True` without `form_edit=True`
  - any mutation verb (`create` / `update` / `delete`) without
    `list=True`

Allowlist entries (by entity `name`) are the explicit, visible
exception register — adding to it is a deliberate "this spec hasn't
been converted to the canonical pattern yet" decision pointing at a
tracking PR / issue, not a default escape valve. Empty allowlist is
the goal.

Layered against `template_component_check.py` (forbids raw HTML
primitives in domain templates) and `template_route_check.py`
(forbids hardcoded URL literals): together they pin URL shape, HTML
shape, and route-spec shape so the canonical resource pattern can't
drift in any single layer.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# Entity `name`s that are known violators with a planned conversion
# stacked behind them. Removing a name here lands when the conversion
# PR for that resource ships.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # The four clinician sub-resources predate parent-aware
        # mount_list / mount_form. Conversion PRs land one at a time
        # off the framework-prep PR that adds parent-aware support.
        "clinician_licensure",
        "clinician_education",
        "clinician_certification",
        "clinician_affiliation",
        # `org_representation` is a headless resource: a User↔Org
        # authority carrier mutated via JSON-only mutations from
        # affordances embedded on `/organizations/{id}` and
        # `/users/{id}` (the OrgRepresentation README documents the
        # claim-B flow). No dedicated list / form pages, by design.
        # If a dedicated chrome ever lands, remove this entry.
        "org_representation",
    }
)


@dataclass(frozen=True)
class _Violation:
    spec_name: str
    missing_verbs: tuple[str, ...]
    implied_by: tuple[str, ...]

    def message(self) -> str:
        missing = ", ".join(self.missing_verbs)
        because = ", ".join(self.implied_by)
        return (
            f"{self.spec_name!r}: declares {because} but missing {missing}. "
            "See RESOURCE_GRAMMAR.md § 'A GET is either a read view or a form.'"
        )


def _check_spec(spec) -> _Violation | None:
    """Return a violation if ``spec.routes`` is off-grammar, else None.

    Walks the implication chain:
      * `create=True` ⇒ `form_new=True`
      * `update=True` ⇒ `form_edit=True`
      * any of `{create, update, delete}` ⇒ `list=True`
    """
    routes = spec.routes
    missing: list[str] = []
    implied_by: list[str] = []
    if routes.create and not routes.form_new:
        missing.append("form_new")
        implied_by.append("create")
    if routes.update and not routes.form_edit:
        missing.append("form_edit")
        implied_by.append("update")
    if (routes.create or routes.update or routes.delete) and not routes.list:
        missing.append("list")
        mutates = [v for v in ("create", "update", "delete") if getattr(routes, v)]
        implied_by.extend(mutates)
    if not missing:
        return None
    return _Violation(
        spec_name=spec.name,
        missing_verbs=tuple(missing),
        implied_by=tuple(dict.fromkeys(implied_by)),  # de-dupe, preserve order
    )


def _all_specs() -> list:
    """Top-level registered specs plus their owned-subentity children.

    Owned subentities (like the credential trio) live on
    ``parent.children`` rather than in ``entity_registry`` directly —
    they aren't independently registered. The walk goes one level
    deep, matching the codebase's current single-level nesting.
    """
    from src.framework.dispatch.registry import entity_registry

    out = []
    for spec in entity_registry.specs():
        out.append(spec)
        out.extend(spec.children)
    return out


def find_violations() -> list[_Violation]:
    """Spec-route grammar violations not covered by `ALLOWLIST`."""
    # Importing the routes package triggers `register_entity` side
    # effects across every entity, populating the registry.
    import src.domain.routes  # noqa: F401

    out: list[_Violation] = []
    for spec in _all_specs():
        if spec.name in ALLOWLIST:
            continue
        violation = _check_spec(spec)
        if violation is not None:
            out.append(violation)
    return out


def main() -> int:
    violations = find_violations()
    if violations:
        print("❌ EntitySpec route-grammar violations:", file=sys.stderr)
        for v in violations:
            print(f"  {v.message()}", file=sys.stderr)
        print(
            "\nDeclare the missing routes on the spec's `RouteSet(...)` "
            "and add the matching templates, or add the spec name to "
            "`ALLOWLIST` in this script (with a one-line note pointing "
            "at the planned conversion PR).",
            file=sys.stderr,
        )
        return 1
    print("✅ No EntitySpec route-grammar violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
