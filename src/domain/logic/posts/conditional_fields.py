"""Conditional-required field rules for the referral wire schema.

One home for the recurring **"field B is required iff a predicate over
field A holds"** pattern on referrals:

  * in-person session selected            → a city/area is required
  * "Other" picked in a multi-select       → its paired ``<field>_other_text``
    free-text is required (``services`` / ``insurance_carriers`` /
    ``languages`` / ``pronouns``)
  * in-network accepted                    → at least one carrier is required

Two consumers read this one list, so "which field is conditional on
what" is stated exactly once:

  * `schema.py` — ``ReferralCreate`` / ``ReferralUpdate`` call
    :func:`enforce_conditional_required` from a ``model_validator(mode=
    "after")``. Each violation is raised as a *field-targeted* error
    (located at the dependent field name) so
    ``build_form_errors_dict`` lands the message on that field's form
    control rather than at the form root.
  * the referral form + its reveal CSS — each rule's
    :attr:`~ConditionalRequiredRule.reveal_token` drives the
    ``:has()``-based show/hide, so the field the server may reject is
    exactly the field the form reveals/hides. See
    ``templates/posts/_form_referral.html`` and the ``conditional-field``
    rules in the domain stylesheet.

Partial updates: a rule whose *trigger* field is absent from the patch
(value ``None``) is skipped — see
:meth:`ConditionalRequiredRule.is_triggered`. The edit form always
submits the full field set, so this only relaxes sparse API PATCHes.
"""

from dataclasses import dataclass
from typing import Any, Callable

from pydantic_core import InitErrorDetails, PydanticCustomError
from pydantic_core import ValidationError as CoreValidationError


def _str_empty(value: Any) -> bool:
    """True when an optional free-text value is missing/blank."""
    return not (value or "").strip()


@dataclass(frozen=True)
class ConditionalRequiredRule:
    """One conditional-required rule.

    ``field`` is the dependent field — also the error ``loc`` and the
    form control's ``name`` (so the inline error renders on it).
    ``trigger_field`` / ``trigger_value`` describe what activates the
    rule and double as the form's reveal selector (see
    :attr:`reveal_token`): ``trigger_value=None`` means a boolean-truthy
    trigger (a single checkbox); a string means "this token is checked in
    the multi-select ``trigger_field``" (e.g. ``other`` in ``services``).
    """

    field: str
    trigger_field: str
    trigger_value: str | None
    message: str
    # Whether the dependent value counts as empty (→ rule violated when
    # triggered). Defaults to the optional-free-text check.
    is_empty: Callable[[Any], bool] = lambda m: True
    # The dependent's current value for the error payload. Defaults to a
    # plain attribute read; nested dependents (``location.city``) override.
    current: Callable[[Any], Any] | None = None

    def is_triggered(self, model: Any) -> bool | None:
        """Is the dependent required for this payload?

        ``None`` means "can't tell" — the trigger field was absent on a
        partial update; callers skip the rule. ``True``/``False`` are
        decisive.
        """
        raw = getattr(model, self.trigger_field)
        if raw is None:
            return None
        if self.trigger_value is None:
            return bool(raw)
        return self.trigger_value in raw

    @property
    def reveal_token(self) -> str:
        """The ``data-reveal-when`` / checkbox-value token the form's
        ``:has()`` selector matches (boolean triggers post ``"true"``)."""
        return f"{self.trigger_field}:{self.trigger_value or 'true'}"

    def current_value(self, model: Any) -> Any:
        return (
            self.current(model)
            if self.current is not None
            else getattr(model, self.field, None)
        )


def _other_text_rule(list_field: str, label: str) -> ConditionalRequiredRule:
    """Rule for the uniform ``"other" in <list> → <list>_other_text required``
    shape. The dependent name is derived, so adding a fourth/fifth
    other-text field is one line here."""
    field = f"{list_field}_other_text"
    return ConditionalRequiredRule(
        field=field,
        trigger_field=list_field,
        trigger_value="other",
        message=f"Required because you selected “Other” for {label}.",
        is_empty=lambda m, _f=field: _str_empty(getattr(m, _f)),
    )


# The whole referral conditional-required contract, in declaration order.
REFERRAL_CONDITIONAL_RULES: tuple[ConditionalRequiredRule, ...] = (
    ConditionalRequiredRule(
        field="location_city",
        trigger_field="session_format",
        trigger_value="in_person",
        message="A city or area is required for in-person sessions.",
        is_empty=lambda m: (
            _str_empty(getattr(m.location, "city", None)) if m.location else True
        ),
        current=lambda m: getattr(m.location, "city", None) if m.location else None,
    ),
    _other_text_rule("services", "Services"),
    _other_text_rule("insurance_carriers", "Insurance carriers"),
    _other_text_rule("languages", "Languages"),
    _other_text_rule("pronouns", "Pronouns"),
)


def enforce_conditional_required(
    model: Any, rules: tuple[ConditionalRequiredRule, ...] = REFERRAL_CONDITIONAL_RULES
) -> None:
    """Raise a field-targeted ``ValidationError`` for every violated rule.

    No-op when nothing is violated. Each violation is one line-error
    located at the dependent ``field`` name; raising via
    ``from_exception_data`` (rather than a plain ``ValueError``, which
    pydantic locates at the model root) is what lets a *cross-field*
    rule attach its message to a *specific* field's form control.
    """
    line_errors: list[InitErrorDetails] = []
    for rule in rules:
        if rule.is_triggered(model) and rule.is_empty(model):
            line_errors.append(
                {
                    "type": PydanticCustomError("conditional_required", rule.message),
                    "loc": (rule.field,),
                    "input": rule.current_value(model),
                }
            )
    if line_errors:
        raise CoreValidationError.from_exception_data(type(model).__name__, line_errors)
