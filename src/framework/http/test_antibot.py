"""Tests for the anti-bot helper (`antibot.py`).

`verify_turnstile` is exercised with `httpx.MockTransport` (the
`test_nppes.py` pattern — no real network). `enforce_antibot` is driven
with hand-built Starlette `Request`s over both body encodings; its
captcha branch monkeypatches `verify_turnstile` so the enforcement logic
is tested without touching the network (the verify function has its own
transport-level coverage above).
"""

import httpx
import pytest

from src.framework.config import settings
from src.framework.http import antibot
from src.framework.http.antibot import (
    HONEYPOT_FIELD,
    TURNSTILE_TOKEN_FIELD,
    BotChallengeFailed,
    enforce_antibot,
    verify_turnstile,
)

pytestmark = pytest.mark.asyncio


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _make_request(
    body: bytes,
    content_type: str,
    client: tuple[str, int] | None = ("1.2.3.4", 12345),
):
    """Build a minimal POST `Request` whose body reads back as `body`."""
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", content_type.encode())],
        "query_string": b"",
        "client": client,
    }
    return Request(scope, receive)


# --- verify_turnstile ------------------------------------------------------


async def test_verify_turnstile_true_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "siteverify" in str(request.url)
        return httpx.Response(200, json={"success": True})

    async with _mock_client(handler) as http:
        assert await verify_turnstile("tok", "1.2.3.4", http=http) is True


async def test_verify_turnstile_false_when_success_false():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error-codes": ["bad"]})

    async with _mock_client(handler) as http:
        assert await verify_turnstile("tok", None, http=http) is False


async def test_verify_turnstile_fails_closed_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    async with _mock_client(handler) as http:
        assert await verify_turnstile("tok", None, http=http) is False


async def test_verify_turnstile_fails_closed_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated network failure")

    async with _mock_client(handler) as http:
        assert await verify_turnstile("tok", None, http=http) is False


async def test_verify_turnstile_fails_closed_on_non_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    async with _mock_client(handler) as http:
        assert await verify_turnstile("tok", None, http=http) is False


# --- enforce_antibot: honeypot (always on) ---------------------------------


async def test_enforce_antibot_rejects_filled_honeypot_json():
    req = _make_request(
        f'{{"email": "a@b.com", "{HONEYPOT_FIELD}": "http://spam"}}'.encode(),
        "application/json",
    )
    with pytest.raises(BotChallengeFailed):
        await enforce_antibot(req)


async def test_enforce_antibot_rejects_filled_honeypot_form():
    req = _make_request(
        f"username=a%40b.com&{HONEYPOT_FIELD}=spam".encode(),
        "application/x-www-form-urlencoded",
    )
    with pytest.raises(BotChallengeFailed):
        await enforce_antibot(req)


async def test_enforce_antibot_passes_empty_honeypot_captcha_disabled(monkeypatch):
    monkeypatch.setattr(settings, "CAPTCHA_ENABLED", False)
    req = _make_request(b'{"email": "a@b.com"}', "application/json")
    # No raise == pass.
    assert await enforce_antibot(req) is None


async def test_enforce_antibot_ignores_blank_honeypot(monkeypatch):
    """A present-but-blank honeypot (real browsers submit empty inputs)
    must not trip the trap."""
    monkeypatch.setattr(settings, "CAPTCHA_ENABLED", False)
    req = _make_request(
        f'{{"email": "a@b.com", "{HONEYPOT_FIELD}": "  "}}'.encode(),
        "application/json",
    )
    assert await enforce_antibot(req) is None


async def test_enforce_antibot_tolerates_malformed_body(monkeypatch):
    monkeypatch.setattr(settings, "CAPTCHA_ENABLED", False)
    req = _make_request(b"not json at all", "application/json")
    # Malformed body → empty dict → honeypot empty → passes.
    assert await enforce_antibot(req) is None


# --- enforce_antibot: Turnstile (gated) ------------------------------------


async def test_enforce_antibot_rejects_missing_token_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "CAPTCHA_ENABLED", True)
    req = _make_request(b'{"email": "a@b.com"}', "application/json")
    with pytest.raises(BotChallengeFailed):
        await enforce_antibot(req)


async def test_enforce_antibot_passes_when_token_verifies(monkeypatch):
    monkeypatch.setattr(settings, "CAPTCHA_ENABLED", True)

    async def _fake_verify(token, remoteip, *, http):
        assert token == "good-token"
        return True

    monkeypatch.setattr(antibot, "verify_turnstile", _fake_verify)
    req = _make_request(
        f'{{"email": "a@b.com", "{TURNSTILE_TOKEN_FIELD}": "good-token"}}'.encode(),
        "application/json",
    )
    assert await enforce_antibot(req) is None


async def test_enforce_antibot_rejects_when_token_invalid(monkeypatch):
    monkeypatch.setattr(settings, "CAPTCHA_ENABLED", True)

    async def _fake_verify(token, remoteip, *, http):
        return False

    monkeypatch.setattr(antibot, "verify_turnstile", _fake_verify)
    req = _make_request(
        f'{{"email": "a@b.com", "{TURNSTILE_TOKEN_FIELD}": "bad-token"}}'.encode(),
        "application/json",
    )
    with pytest.raises(BotChallengeFailed):
        await enforce_antibot(req)
