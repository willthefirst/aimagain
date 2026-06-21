"""`LabeledChoice` — one type per controlled vocabulary, single source of truth.

A controlled vocabulary (e.g. treatment modalities) needs three artifacts that
must never drift apart: the set of storage values (CHECK constraint, Pydantic
`Literal`, seed pool), the human label per value (form options, listing rows),
and — for some vocabularies — an icon per value. The old shape kept these as a
`Final[tuple]` and one or two parallel `Final[dict]`s; adding a member meant
editing every parallel structure in lockstep, and a guardrail test existed only
to catch when someone forgot.

`LabeledChoice` collapses them into one `enum.StrEnum` subclass: each member
declares its value, label, and optional icon together, so they can't drift.
Members ARE `str` (StrEnum), so a member round-trips through Pydantic, JSON, and
SQLAlchemy Text columns byte-identically to the bare string it replaces — code
that compares against or stores the plain value keeps working unchanged.

Derived artifacts come off the class, so downstream stays declarative:

    class SessionFormat(LabeledChoice):
        in_person = "in_person", "In-person"
        virtual = "virtual", "Virtual"

    SessionFormat.values()   # ("in_person", "virtual")           -> Literal / CHECK / seed
    SessionFormat.labels()   # {"in_person": "In-person", ...}    -> form options, rows
    SessionFormat.choices()  # (("in_person", "In-person"), ...)  -> ordered (value, label)

Members with an icon pass a third element; `icons()` then maps value -> icon
(`None` for members that omit it):

    class ReferralService(LabeledChoice):
        psychotherapy = "psychotherapy", "Psychotherapy", "brain"

    ReferralService.icons()  # {"psychotherapy": "brain", ...}

A vocabulary with no display labels (a status enum) declares value-only members;
`label` then falls back to the value, so `labels()` stays total:

    class VerificationStatus(LabeledChoice):
        verified = "verified"
        failed = "failed"

A vocabulary whose display facts are richer than value+label+icon (a cohort
with a singular/plural noun and a numeric range, a weekday with both a long and
a short label) subclasses with its own `__new__` that attaches the extra
attributes — and still sets `label`/`icon` so the derived artifacts stay total.
See `ClientAgeGroup` / `DesiredTimeDay` in `enums.py`.

A *leaf* — imports only the stdlib — so any model cluster can import it without
cycling, same as `enums.py`.
"""

import enum


class LabeledChoice(enum.StrEnum):
    label: str
    icon: "str | None"

    def __new__(
        cls, value: str, label: "str | None" = None, icon: "str | None" = None
    ) -> "LabeledChoice":
        obj = str.__new__(cls, value)
        obj._value_ = value
        # A value-only member (`status = "verified"`) is a vocabulary with no
        # display labels — `.label` falls back to the storage value so the
        # derived `labels()` dict is still total.
        obj.label = value if label is None else label
        obj.icon = icon
        return obj

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Storage values in declaration order — feeds `Literal`, CHECK, seed."""
        return tuple(m.value for m in cls)

    @classmethod
    def labels(cls) -> dict[str, str]:
        """`value -> label` — feeds form options and listing-row rendering."""
        return {m.value: m.label for m in cls}

    @classmethod
    def choices(cls) -> tuple[tuple[str, str], ...]:
        """Ordered `(value, label)` pairs — feeds filter specs and `<select>`s."""
        return tuple((m.value, m.label) for m in cls)

    @classmethod
    def icons(cls) -> dict[str, "str | None"]:
        """`value -> icon` (Lucide name), `None` where a member omits one."""
        return {m.value: m.icon for m in cls}
