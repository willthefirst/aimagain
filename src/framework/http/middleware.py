"""Custom ASGI middleware shared across the application.

Each middleware here exists to enforce a convention at the request-entry
boundary, before FastAPI's parameter binding runs — once at the layer
where the convention belongs, instead of every handler remembering it.
"""

from typing import Callable

from starlette.datastructures import MutableHeaders


class StaticNoCacheMiddleware:
    """Add ``Cache-Control: no-store`` to every ``/static/`` response.

    Prevents the browser from caching CSS/JS/font assets between reloads
    so edits are visible without a hard refresh. Only mount this in
    development — production static assets should be far-future cached.
    """

    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/static/"):

            async def send_no_cache(message):
                if message["type"] == "http.response.start":
                    headers = MutableHeaders(scope=message)
                    headers["Cache-Control"] = "no-store"
                await send(message)

            await self.app(scope, receive, send_no_cache)
        else:
            await self.app(scope, receive, send)


class StaticLongCacheMiddleware:
    """Add ``Cache-Control`` to ``/static/`` responses in production.

    Lighthouse flags Starlette's bare ``StaticFiles`` (no
    ``Cache-Control`` at all) as "Use efficient cache lifetimes" —
    repeat visitors re-download every CSS file on every navigation.

    Two TTLs, distinguished by the presence of a ``?v=`` query string:

    - **Versioned URLs** (``/static/...?v=<sha>``) → 1 year + immutable.
      The convention is that the version sentinel comes from
      ``settings.APP_RELEASE`` via the ``static_version`` Jinja global,
      so a deploy of a new SHA mints fresh URLs and busts the cache
      cleanly. ``immutable`` tells the browser to skip even conditional
      revalidation while the entry is fresh.
    - **Unversioned URLs** → 5 min with ``must-revalidate``. Safe
      default for hot-linked assets and for environments where
      ``APP_RELEASE`` is empty (``static_version`` evaluates to ``""``
      and the templates omit the ``?v=`` segment entirely). ETag-driven
      304s still keep the wire cost near zero on repeat hits.

    Mounted in production only. ``StaticNoCacheMiddleware`` covers the
    dev-loop case.
    """

    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/static/"):
            await self.app(scope, receive, send)
            return

        is_versioned = b"v=" in scope.get("query_string", b"")
        header_value = (
            "public, max-age=31536000, immutable"
            if is_versioned
            else "public, max-age=300, must-revalidate"
        )

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = header_value
            await send(message)

        await self.app(scope, receive, send_with_cache)


class StripEmptyQueryParamsMiddleware:
    """Treat ``?key=`` (and bare ``?key``) as if the key were absent.

    HTML forms submit every named field, including empty ``<select>``s
    (``value=""``) — without this middleware FastAPI binds the empty
    string instead of falling back to the route's declared default.
    Trade-off: routes cannot distinguish "client sent empty" from "client
    omitted"; use an explicit sentinel (``?x=__empty__``) if needed.
    """

    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            qs: bytes = scope.get("query_string", b"")
            if qs:
                stripped = _strip_empty_pairs(qs)
                if stripped != qs:
                    scope = {**scope, "query_string": stripped}
        await self.app(scope, receive, send)


def _strip_empty_pairs(query_string: bytes) -> bytes:
    """Return `query_string` with empty-valued pairs removed.

    A pair is "empty" when the bytes after the first ``=`` are empty,
    or when the pair contains no ``=`` at all (flag-style key with no
    value). Everything else passes through unchanged — whitespace
    values (``key=%20``) are real values and are kept.
    """
    kept: list[bytes] = []
    for pair in query_string.split(b"&"):
        if not pair:
            continue
        eq = pair.find(b"=")
        if eq == -1:
            # `?key` with no `=` — flag-style, treated as no value.
            continue
        if eq == len(pair) - 1:
            # `?key=` — value is empty.
            continue
        kept.append(pair)
    return b"&".join(kept)
