"""`StaticFiles` subclass that minifies CSS responses in-process.

Wired into `src/main.py` for non-development environments. In dev we
serve raw CSS so DevTools shows readable source; in prod the same
mounts go through this subclass so framework.css and domain.css are
served as minified bytes (Lighthouse: "minify-css" audit). The
per-process minified-bytes cache means the file is read + minified
exactly once for the lifetime of the container.
"""

from __future__ import annotations

import re
import stat
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

_COMMENT_RE = re.compile(r"/\*.*?\*/", flags=re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")
_ADJACENT_PUNCTUATION_RE = re.compile(r"\s*([{};:,>+~])\s*")


def minify_css(source: str) -> str:
    """Strip comments + collapse whitespace in a CSS file.

    Conservative: handles the subset our hand-written CSS uses
    (no inline `data:` URLs in string literals, no unusual selectors
    that depend on inter-token whitespace). The two production files
    today (`framework.css`, `domain.css`) are plain Pico-based
    overrides. Revisit if a future addition crosses a corner case
    (the test in `test_static_files.py` will surface visible
    regressions).
    """
    source = _COMMENT_RE.sub("", source)
    source = _WHITESPACE_RE.sub(" ", source)
    source = _ADJACENT_PUNCTUATION_RE.sub(r"\1", source)
    source = source.replace(";}", "}")
    return source.strip()


class MinifyingStaticFiles(StaticFiles):
    """Serve CSS files minified, everything else verbatim.

    The cache is keyed by lookup path → ``(etag, minified_bytes)`` and
    is populated lazily on first request per path. Process-lifetime
    only — a deploy (new container) starts fresh. Conditional GETs
    (``If-None-Match``) are honored against the minified ETag so a
    revalidating browser gets a 304 without re-reading the file.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._css_cache: dict[str, tuple[str, bytes]] = {}

    async def get_response(self, path: str, scope: Scope) -> Response:
        if not path.endswith(".css") or scope["method"] not in ("GET", "HEAD"):
            return await super().get_response(path, scope)

        entry = self._css_cache.get(path)
        if entry is None:
            import anyio

            full_path, st = await anyio.to_thread.run_sync(self.lookup_path, path)
            if not st or not stat.S_ISREG(st.st_mode):
                return await super().get_response(path, scope)
            with open(full_path, "rb") as fh:
                raw = fh.read().decode("utf-8")
            minified = minify_css(raw).encode("utf-8")
            # Weak ETag shape (mtime + minified size). Computed against
            # the *minified* bytes so comment-only source edits don't
            # bust the client cache unnecessarily.
            etag = f'W/"{int(st.st_mtime):x}-{len(minified):x}"'
            entry = (etag, minified)
            self._css_cache[path] = entry

        etag, body = entry
        request_headers = Headers(scope=scope)
        if request_headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})

        return Response(
            content=body,
            media_type="text/css",
            headers={"ETag": etag},
        )
