"""Declarative filter types for list-page query params.

A ``Filter`` is a richer ``QueryParam`` — same URL contract (it
becomes a FastAPI ``Query(...)`` on the list route via
``to_query_param()``) plus rendering metadata the templates read to
pick the right HTML control (search input, single ``<select>``,
multi-choice ``<fieldset>`` of checkboxes, radio-toggle group).

The split is deliberate: the URL shape and the UI shape change for
different reasons. A column may stay queryable from a URL while the
rendered control changes; a control may change kind without altering
the param name. ``Filter`` keeps both axes declarative without
collapsing them into one boolean.

``EntitySpec.filters`` accepts either a raw ``QueryParam`` (legacy)
or a ``Filter`` instance — the mount layer normalizes both to
``QueryParam`` before handing them to FastAPI, and the
``handle_list`` factory threads the same names through to the repo's
bespoke ``list_<collection>`` method.

Every declared ``Filter`` renders as a form control on the
dedicated ``/<collection>/search`` page (see
``framework/templates/views/search.html``). The list-page toolbar
has only the "Filter · N" link (on the left) and the page-action
menu (on the right); the active-filter strip below it lists each
active value as a removable tag (each tag a small ``<form>`` that
resubmits the URL minus that one filter).
"""

from dataclasses import dataclass
from typing import Any, ClassVar

from src.framework.dispatch.resource_routes import QueryParam


@dataclass(frozen=True)
class Filter:
    """Base class for declarative filter types.

    Subclasses set ``kind`` (read by the template macro) and override
    ``annotation`` / ``default`` to match the URL contract for that
    filter type. ``to_query_param()`` returns the ``QueryParam`` the
    existing mount layer already consumes — Filter is layered *on
    top of* QueryParam, not a replacement.

    Fields:
      name:  query-param name (also the kwarg the repo's bespoke
             ``list_<collection>`` method receives).
      label: human label rendered above the control in the filter
             form. Empty string falls back to ``name``.
    """

    name: str
    label: str = ""

    kind: ClassVar[str] = ""

    @property
    def annotation(self) -> Any:
        raise NotImplementedError

    @property
    def default(self) -> Any:
        raise NotImplementedError

    def to_query_param(self) -> QueryParam:
        return QueryParam(
            name=self.name, annotation=self.annotation, default=self.default
        )

    @property
    def display_label(self) -> str:
        return self.label or self.name


@dataclass(frozen=True)
class TextFilter(Filter):
    """Free-text filter rendered as ``<input type="search">``.

    URL: ``?<name>=<query>``. Empty / absent param skips the filter.
    Repo applies an ``ILIKE %query%`` against one or more columns —
    the repo owns the SQL because the column set is entity-specific
    (and often polymorphic).
    """

    placeholder: str = ""

    kind: ClassVar[str] = "text"

    @property
    def annotation(self) -> Any:
        return str | None

    @property
    def default(self) -> Any:
        return None


@dataclass(frozen=True)
class ChoiceFilter(Filter):
    """Fixed-value filter rendered as ``<select>`` or a checkbox group.

    ``choices`` is a tuple of ``(value, label)`` pairs. ``multi=True``
    renders a ``<fieldset class="search-checkbox-fieldset">`` of
    single-click checkboxes (one per choice) and parses repeated query
    params (``?<name>=a&<name>=b``) into a list — replacing the prior
    ``<select multiple>`` listbox whose cmd/ctrl-click UX the audit
    flagged (#583). ``multi=False`` renders a single ``<select>`` with
    an "Any" placeholder. Pass ``radio=True`` (single-select only) to
    render a Pico-style toggle radio-button group instead — an "Any"
    reset option is prepended automatically. ``radio`` is ignored when
    ``multi=True``.

    The ``annotation`` defaults to permissive (``str | None`` /
    ``list[str]``) so adding a value to the choice set doesn't
    require a code change — pass ``value_type=Literal[...]`` to
    tighten validation when the choice universe is fixed at startup
    (e.g. post kinds).
    """

    choices: tuple[tuple[str, str], ...] = ()
    multi: bool = False
    radio: bool = False
    value_type: Any = None  # tighten annotation; defaults to `str`
    size: int = 6

    kind: ClassVar[str] = "choice"

    @property
    def annotation(self) -> Any:
        item_type = self.value_type if self.value_type is not None else str
        if self.multi:
            return list[item_type] | None
        return item_type | None

    @property
    def default(self) -> Any:
        return None


@dataclass(frozen=True)
class FlagFilter(Filter):
    """Present-or-absent boolean rendered as a single labeled checkbox.

    URL: ``?<name>=1`` when checked, omitted when unchecked. Absent param
    means the filter is inactive. The repo receives the string ``"1"``
    (truthy) or ``None`` (absent).

    ``label_checked`` is the label rendered next to the checkbox. Falls
    back to ``display_label`` when not set.
    """

    label_checked: str = ""

    kind: ClassVar[str] = "flag"

    @property
    def annotation(self) -> Any:
        return str | None

    @property
    def default(self) -> Any:
        return None
