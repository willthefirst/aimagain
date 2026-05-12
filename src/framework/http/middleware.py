"""Custom ASGI middleware shared across the application.

Each middleware here exists to enforce a convention at the request-entry
boundary, before FastAPI's parameter binding runs — once at the layer
where the convention belongs, instead of every handler remembering it.
"""

from typing import Callable


class StripEmptyQueryParamsMiddleware:
    """Treat ``?key=`` (and ``?key`` with no ``=``) as if the key were
    absent from the URL.

    HTML forms submit every named field's current value, including
    empty selections (``<select>`` whose selected option has
    ``value=""``). Without this middleware, a route declaring
    ``filter: str | None = None`` receives the empty string instead of
    its declared default — the default only fires when FastAPI binds
    no value for the parameter, and ``?filter=`` is "value bound to
    empty string", not "value absent". Likewise a ``Literal[...]``
    param with a default 422s on an empty submission instead of
    falling back to the default.

    Stripping empty pairs at the URL layer encodes the HTML-form
    convention ("empty = no opinion") once, so every route's declared
    default fires naturally and no per-handler coercion is needed.

    The trade-off: a route can no longer distinguish "client sent
    ``?x=`` deliberately" from "client omitted ``?x=``". If a future
    route genuinely needs that distinction it should use a non-empty
    sentinel value (``?x=__empty__``) and decode it explicitly — that
    is the convention every other major API uses for the same
    situation, since browsers can't be coaxed into omitting empty
    fields without per-form JavaScript.
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
