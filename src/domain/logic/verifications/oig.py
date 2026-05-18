"""OIG/LEIE exclusion-list lookup.

The Office of Inspector General publishes the List of Excluded
Individuals/Entities (LEIE) as a CSV refreshed monthly:
https://oig.hhs.gov/exclusions/exclusions_list.asp. We load the file
on first call and cache an in-memory index keyed by NPI and by
``(FIRSTNAME, LASTNAME)`` (both upper-cased). A miss is a "no match";
a hit is a hard disqualifier in the scoring layer.

Pure function — no DB, no FastAPI, no `httpx`. Operator-driven file
refresh; see the README in this directory for the cadence.
"""

import csv
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# Default location matches `deployment/`'s convention of "operator-managed
# bulk data lives under `data/`." Override via `LEIE_CSV_PATH` for tests
# or alternate deployments.
_LEIE_PATH_ENV = "LEIE_CSV_PATH"
_DEFAULT_LEIE_PATH = "data/LEIE.csv"


MatchReason = Literal["npi_match", "name_match"]


@dataclass(frozen=True, slots=True)
class OigResult:
    """Outcome of a single OIG/LEIE check.

    `match=True` is a hard disqualifier in the scoring layer. `reason`
    is surfaced as a `flag` on the `Verification` row so a human reviewer
    can tell at a glance whether it was an NPI hit (high confidence) or
    a name hit (lower confidence — names are not unique).
    """

    match: bool
    reason: MatchReason | None


_NO_MATCH = OigResult(match=False, reason=None)


@dataclass(frozen=True, slots=True)
class _LeieIndex:
    """Two lookup dicts built once on first load: by NPI (only for rows
    where the CSV's NPI column is non-empty) and by `(FIRSTNAME, LASTNAME)`
    upper-cased. Both values are always ``True`` — we only need
    set-membership semantics, but keeping it a dict means a future
    extension can replace the value with the matched row without
    rewriting the lookup."""

    by_npi: dict[str, bool]
    by_name: dict[tuple[str, str], bool]


_INDEX_CACHE: dict[str, _LeieIndex] = {}


def _load_index(path: str) -> _LeieIndex | None:
    """Parse the LEIE CSV at `path` into an `_LeieIndex`, or return
    ``None`` if the file is missing. The parsed index is cached by
    absolute path so a second call with the same path skips re-parsing
    the ~80MB file. A missing file is logged once and not retried per
    process — operators get a noisy startup signal without the per-call
    log spam.
    """
    resolved = str(Path(path).resolve())
    if resolved in _INDEX_CACHE:
        return _INDEX_CACHE[resolved]

    if not Path(path).is_file():
        logger.warning(
            "oig_check: LEIE CSV not found at %s (set %s to override). "
            "Returning no-match for every check.",
            path,
            _LEIE_PATH_ENV,
        )
        return None

    by_npi: dict[str, bool] = {}
    by_name: dict[tuple[str, str], bool] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            npi = (row.get("NPI") or "").strip()
            if npi:
                by_npi[npi] = True
            first = (row.get("FIRSTNAME") or "").strip().upper()
            last = (row.get("LASTNAME") or "").strip().upper()
            if first and last:
                by_name[(first, last)] = True

    index = _LeieIndex(by_npi=by_npi, by_name=by_name)
    _INDEX_CACHE[resolved] = index
    logger.info(
        "oig_check: loaded LEIE index from %s (%d NPI keys, %d name keys)",
        resolved,
        len(by_npi),
        len(by_name),
    )
    return index


def _csv_path() -> str:
    return os.getenv(_LEIE_PATH_ENV, _DEFAULT_LEIE_PATH)


def oig_check(*, first_name: str, last_name: str, npi: str | None) -> OigResult:
    """Check whether `(first_name, last_name)` or `npi` appears on the
    LEIE exclusion list. NPI hits win (higher confidence — NPIs are
    unique to a provider); name-only hits fall through and are surfaced
    with ``reason='name_match'`` so the reviewer knows.
    """
    index = _load_index(_csv_path())
    if index is None:
        return _NO_MATCH

    if npi and npi in index.by_npi:
        return OigResult(match=True, reason="npi_match")

    key = (first_name.strip().upper(), last_name.strip().upper())
    if all(key) and key in index.by_name:
        return OigResult(match=True, reason="name_match")

    return _NO_MATCH


def _reset_cache_for_tests() -> None:
    """Clear the module-level cache. Tests that exercise different
    fixture CSVs in the same process must call this between cases —
    the cache is by absolute path so distinct fixtures don't collide,
    but a test that rewrites the same path in place would otherwise see
    stale data."""
    _INDEX_CACHE.clear()
