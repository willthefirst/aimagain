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


@dataclass(frozen=True, slots=True)
class NppesOrgResult:
    """Outcome of a Type-2 NPPES lookup. Mirrors `NppesResult` for the
    org case: `org_name` drives the org-name similarity score against
    `Organization.name`; `authorized_official_name` is what the
    `authorized_official` authority-method path matches against the
    requesting user's verified `Clinician` legal name (handoff §6)."""

    found: bool
    org_name: str | None
    authorized_official_name: str | None
    raw: dict[str, Any] | None


_ORG_NOT_FOUND = NppesOrgResult(
    found=False, org_name=None, authorized_official_name=None, raw=None
)


async def nppes_lookup_type2(npi: str, *, http: httpx.AsyncClient) -> NppesOrgResult:
    """Look up a Type-2 (organizational) NPI against NPPES.

    Same degraded-on-failure contract as `nppes_lookup`: the function
    never raises so the orchestrator always gets a `Verification` row.
    NPPES distinguishes Type-1 from Type-2 via the `enumeration_type`
    field on the result (`"NPI-2"` for orgs); if the lookup returns a
    Type-1 we treat it as not-found for org purposes — calling code
    should never pass a Type-1 NPI here.

    The Type-2 payload's `basic` block has different fields than Type-1:
    `organization_name` instead of `first_name`/`last_name`, plus
    `authorized_official_first_name` / `authorized_official_last_name` /
    `authorized_official_middle_name` for the AO name-match path.
    """
    try:
        response = await http.get(
            _NPPES_ENDPOINT,
            params={
                "version": _NPPES_VERSION,
                "number": npi,
                "enumeration_type": "NPI-2",
            },
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.warning("nppes_lookup_type2(%s): request failed: %s", npi, exc)
        return _ORG_NOT_FOUND

    if response.status_code >= 400:
        logger.warning(
            "nppes_lookup_type2(%s): unexpected status %s",
            npi,
            response.status_code,
        )
        return _ORG_NOT_FOUND

    try:
        payload: dict[str, Any] = response.json()
    except ValueError as exc:
        logger.warning("nppes_lookup_type2(%s): non-JSON payload: %s", npi, exc)
        return _ORG_NOT_FOUND

    results = payload.get("results") or []
    if not results:
        return NppesOrgResult(
            found=False,
            org_name=None,
            authorized_official_name=None,
            raw=payload,
        )

    result0 = results[0] or {}
    if result0.get("enumeration_type") not in (None, "NPI-2"):
        # Defensive: NPPES returned a Type-1 record despite the
        # `enumeration_type=NPI-2` filter. Treat as not-found for org
        # purposes; the worker logs and the row stays `pending`.
        logger.warning(
            "nppes_lookup_type2(%s): enumeration_type=%s (expected NPI-2)",
            npi,
            result0.get("enumeration_type"),
        )
        return NppesOrgResult(
            found=False, org_name=None, authorized_official_name=None, raw=payload
        )

    basic = result0.get("basic") or {}
    org_name = basic.get("organization_name")
    ao_first = basic.get("authorized_official_first_name") or ""
    ao_middle = basic.get("authorized_official_middle_name") or ""
    ao_last = basic.get("authorized_official_last_name") or ""
    ao_parts = [p.strip() for p in (ao_first, ao_middle, ao_last) if p and p.strip()]
    ao_name = " ".join(ao_parts) if ao_parts else None
    return NppesOrgResult(
        found=True,
        org_name=org_name if isinstance(org_name, str) else None,
        authorized_official_name=ao_name,
        raw=payload,
    )
