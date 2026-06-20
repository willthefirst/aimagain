# Saved searches cluster

A user-owned, named filtered view of the post directory. One row = one saved `/posts` filter set, owned by a `User` (1:N, FK `user_id` with `ondelete="CASCADE"`). Routes nest under `/users/{user_id}/saved_searches` — see [`../../specs/saved_search.py`](../../specs/saved_search.py) and the logic cluster [`../../logic/saved_searches/`](../../logic/saved_searches/README.md).

## Files

- `saved_search.py` — `SavedSearch`. Columns: `user_id` (FK, CASCADE), `name` (Text), `filters` (JSON object). `(user_id, name)` is UNIQUE — one name per user.

## Why `filters` is structured JSON, not a stored URL

This is the load-bearing modelling decision. A saved search persists the **`filter_values` dict** — the `{filter_name: value}` shape the `/posts` list route already parses out of its query string (see [`../posts/README.md`](../posts/README.md), `src/domain/specs/posts.py`'s `filters`, and `src/framework/dispatch/mounts/list_.py::handle_list`). The shareable URL is *re-rendered from this dict on demand*, never stored.

The alternative — storing the literal `/posts?kind=...` string — was rejected. Three things drift independently over time:

1. **URL syntax** — how multi-values serialize (`?kind=a&kind=b` vs `?kind=a,b`), or the `/posts` path itself.
2. **Filter names** — a declared filter renamed (`kind` → `category`).
3. **Filter values** — a discriminator value renamed (`clinician_opening` → `opening`).

Structured storage absorbs **#1 for free** (re-render from the live filter spec — no data touched), and turns **#2/#3** into an ordinary JSON-column data migration — the same discipline every persisted-JSON shape in this repo follows. A stored-URL model survives none of the three without a URL-rewriting redirect layer whose rule set grows unbounded, and it can't be validated against the live filter spec to detect staleness. The structured dict can.

`filters` is intentionally **not** SQL-CHECK-constrained against the live post-filter names — same convention as the JSON multi-select columns elsewhere (`programs.services`, `referral_details.age_groups`). The vocabulary is validated on the wire when a search is saved (Pydantic), not by the database. `{}` is a valid value: "no filters", i.e. the whole directory.
