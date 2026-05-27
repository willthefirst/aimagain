"""NPPES (National Plan and Provider Enumeration System) lookup.

Pure function: takes a 10-digit NPI and an `httpx.AsyncClient` (the
orchestrator in #528 / A4 owns the client's lifetime) and returns a
:class:`NppesResult`. Never raises — the orchestrator must always be
able to produce a `Verification` row, even on a registry outage or a
malformed payload. Failures degrade to ``found=False`` and a logged
warning.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Free public registry. No documented rate limit; the nightly job runs
# sequentially anyway. v2.1 is the current contract per the NPPES API docs.
_NPPES_ENDPOINT = "https://npiregistry.cms.hhs.gov/api/"
_NPPES_VERSION = "2.1"
_DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class NppesResult:
    """Outcome of a single NPPES lookup.

    `found` is the only field the scoring layer branches on. The names
    drive the name-similarity score; `raw` is persisted on the
    `Verification` row for audit replay.
    """

    found: bool
    first_name: str | None
    last_name: str | None
    raw: dict[str, Any] | None


_NOT_FOUND = NppesResult(found=False, first_name=None, last_name=None, raw=None)


async def nppes_lookup(npi: str, *, http: httpx.AsyncClient) -> NppesResult:
    """Look up `npi` against the NPPES public API.

    The orchestrator owns the `httpx.AsyncClient` — typically one client
    per nightly-job run, reused across clinicians. 4xx/5xx, timeouts, and
    malformed payloads degrade to ``NppesResult(found=False, ...)`` plus
    a logged warning; this function never raises so the orchestrator can
    always persist a `Verification` row.
    """
    try:
        response = await http.get(
            _NPPES_ENDPOINT,
            params={"version": _NPPES_VERSION, "number": npi},
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.warning("nppes_lookup(%s): request failed: %s", npi, exc)
        return _NOT_FOUND

    if response.status_code >= 400:
        logger.warning(
            "nppes_lookup(%s): unexpected status %s", npi, response.status_code
        )
        return _NOT_FOUND

    try:
        payload: dict[str, Any] = response.json()
    except ValueError as exc:
        logger.warning("nppes_lookup(%s): non-JSON payload: %s", npi, exc)
        return _NOT_FOUND

    results = payload.get("results") or []
    if not results:
        return NppesResult(found=False, first_name=None, last_name=None, raw=payload)

    basic = (results[0] or {}).get("basic") or {}
    first = basic.get("first_name")
    last = basic.get("last_name")
    return NppesResult(
        found=True,
        first_name=first if isinstance(first, str) else None,
        last_name=last if isinstance(last, str) else None,
        raw=payload,
    )
