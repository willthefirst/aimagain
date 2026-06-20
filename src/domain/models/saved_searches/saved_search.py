from sqlalchemy import JSON, Column, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel


class SavedSearch(BaseModel):
    """A user-owned, named filtered view of the post directory.

    A saved search is a persisted ``filter_values`` dict — the same
    ``{filter_name: value}`` shape the ``/posts`` list route parses out
    of its query string and hands to ``PostRepository.list_posts`` (see
    `src/domain/specs/posts.py` for the declared filters and
    `src/framework/dispatch/mounts/list_.py::handle_list`). Storing the
    *structured* filter state rather than a literal URL string is the
    deliberate durability choice: the URL is re-rendered from this dict
    on demand, so changes to URL *syntax* (how multi-values serialize,
    the ``/posts`` path itself) need no migration, and a filter
    *rename* is an ordinary JSON-column data migration — the same
    discipline every persisted-JSON shape in this repo follows. See the
    cluster README for the full rationale.

    ``filters`` is a JSON object; ``{}`` is a valid value meaning "no
    filters" (i.e. the whole directory). The vocabulary inside it is
    *not* SQL-CHECK-constrained against the live post-filter names — the
    same convention the JSON multi-select columns elsewhere follow
    (validation is a wire/Pydantic concern, enforced when a search is
    saved; see `src/domain/logic/saved_searches/schema.py`).

    ``CASCADE`` on the owner FK keeps a user's saved searches in
    lockstep with the user row. ``(user_id, name)`` is UNIQUE: a single
    user can't hold two saved searches with the same name (the default
    seed and any user-created search share one namespace).
    """

    __tablename__ = "saved_searches"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_search_name"),)

    user_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(Text, nullable=False)
    # The persisted filter_values dict. `server_default` + `default`
    # mirror the JSON-object columns elsewhere (e.g. `programs.services`
    # uses `'[]'` for a list home); here the empty *object* `'{}'` is
    # the "no filters" value.
    filters = Column(JSON, nullable=False, server_default=text("'{}'"), default=dict)
