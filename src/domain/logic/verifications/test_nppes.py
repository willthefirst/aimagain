"""Tests for `nppes_lookup`.

Mocks `httpx.AsyncClient` via `httpx.MockTransport` — no real network
calls, no `respx` dep needed. Covers the four branches the orchestrator
relies on: found+names, found+empty-results, 4xx, transport error.
"""

import json

import httpx
import pytest

from src.domain.logic.verifications.nppes import NppesResult, nppes_lookup

pytestmark = pytest.mark.asyncio


def _mock_client(handler) -> httpx.AsyncClient:
    """`httpx`'s built-in mock transport. `handler(request) -> Response`
    runs synchronously; for transport errors raise an `httpx.HTTPError`
    subclass from inside the handler."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_nppes_lookup_returns_names_on_hit():
    payload = {
        "results": [
            {
                "basic": {
                    "first_name": "ALICE",
                    "last_name": "EXAMPLE",
                },
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        # The orchestrator passes `version=2.1&number={npi}` per the API
        # contract — assert here so we don't silently swap to a wrong
        # endpoint shape.
        assert "/api/" in str(request.url)
        assert request.url.params.get("version") == "2.1"
        assert request.url.params.get("number") == "1234567890"
        return httpx.Response(200, json=payload)

    async with _mock_client(handler) as http:
        result = await nppes_lookup("1234567890", http=http)

    assert result == NppesResult(
        found=True,
        first_name="ALICE",
        last_name="EXAMPLE",
        raw=payload,
    )


async def test_nppes_lookup_returns_not_found_on_empty_results():
    """The registry returns 200 with `results: []` when an NPI isn't
    in the database — that's the "not enrolled" signal, not an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    async with _mock_client(handler) as http:
        result = await nppes_lookup("9999999999", http=http)

    assert result.found is False
    assert result.first_name is None
    assert result.last_name is None
    # Raw payload is still preserved so the audit row shows what NPPES
    # said (here: "no match"), distinct from a transport failure.
    assert result.raw == {"results": []}


async def test_nppes_lookup_degrades_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    async with _mock_client(handler) as http:
        result = await nppes_lookup("0000000000", http=http)

    assert result.found is False
    assert result.raw is None


async def test_nppes_lookup_degrades_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    async with _mock_client(handler) as http:
        result = await nppes_lookup("0000000000", http=http)

    assert result.found is False
    assert result.raw is None


async def test_nppes_lookup_degrades_on_transport_error():
    """A network failure (DNS, timeout, dropped connection) raises
    `httpx.HTTPError`; the lookup must swallow it so the orchestrator
    can still produce a row."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    async with _mock_client(handler) as http:
        result = await nppes_lookup("0000000000", http=http)

    assert result.found is False
    assert result.raw is None


async def test_nppes_lookup_degrades_on_non_json_payload():
    """A 200 OK with a non-JSON body is treated as a registry hiccup,
    not a hard failure — the orchestrator still gets a not-found row."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    async with _mock_client(handler) as http:
        result = await nppes_lookup("0000000000", http=http)

    assert result.found is False
    assert result.raw is None


async def test_nppes_lookup_handles_missing_basic_block():
    """A `results[0]` without a `basic` block (or with non-string names)
    falls back to None names but still reports `found=True` — the row
    exists, we just couldn't extract a name to compare."""
    payload = {"results": [{"other_block": {}}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with _mock_client(handler) as http:
        result = await nppes_lookup("1234567890", http=http)

    assert result.found is True
    assert result.first_name is None
    assert result.last_name is None
    assert result.raw == payload


async def test_nppes_lookup_json_roundtrip_through_response():
    """Sanity check that the JSON shape we expect from CMS round-trips
    through `httpx.Response.json()` unchanged."""
    payload = {"results": [{"basic": {"first_name": "X", "last_name": "Y"}}]}
    encoded = json.dumps(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=encoded.encode(), headers={"Content-Type": "application/json"}
        )

    async with _mock_client(handler) as http:
        result = await nppes_lookup("1234567890", http=http)

    assert result.found is True
    assert result.first_name == "X"
    assert result.last_name == "Y"
