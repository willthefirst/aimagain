"""Custom ASGI middleware shared across the application.

Each middleware here exists to enforce a convention at the request-entry
boundary, before FastAPI's parameter binding runs — once at the layer
where the convention belongs, instead of every handler remembering it.
"""

from typing import Callable


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
