"""Tests for `src/framework/email/sender.py`.

Pin the backend-dispatch behavior (the production-mode call shape is
covered via a mocked import — we don't talk to Resend in CI).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.framework.email import send_email


@pytest.mark.asyncio
async def test_console_backend_prints_subject_to_stderr(capsys, monkeypatch):
    """`console` is the safe default. A successful send writes the
    recipient + subject + text body to stderr (the linter/tests can
    capture it) and returns without touching the network."""
    monkeypatch.setattr("src.framework.email.sender.settings.EMAIL_BACKEND", "console")
    monkeypatch.setattr(
        "src.framework.email.sender.settings.EMAIL_FROM", "no-reply@example.com"
    )

    await send_email(
        to="alice@example.com",
        subject="Hello",
        html="<p>Hi</p>",
        text="Hi",
    )

    err = capsys.readouterr().err
    assert "alice@example.com" in err
    assert "Hello" in err
    assert "Hi" in err
    # `From:` line is also part of the dev terminal output so the dev
    # can confirm which sending address they're using without re-reading
    # `.env`.
    assert "no-reply@example.com" in err


@pytest.mark.asyncio
async def test_file_backend_writes_eml_under_mail_dir(tmp_path, monkeypatch):
    """`file` writes a timestamped file under `./.mail/`. The file
    contains the subject, recipient, and both body parts so the dev
    can inspect HTML rendering."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.framework.email.sender.settings.EMAIL_BACKEND", "file")
    monkeypatch.setattr(
        "src.framework.email.sender.settings.EMAIL_FROM", "no-reply@example.com"
    )

    await send_email(
        to="bob@example.com",
        subject="Reset your password",
        html="<p>HTML</p>",
        text="Plain",
    )

    mail_dir = Path(".mail")
    assert mail_dir.is_dir()
    files = list(mail_dir.glob("*.eml"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert "bob@example.com" in body
    assert "Reset your password" in body
    assert "Plain" in body
    assert "<p>HTML</p>" in body


@pytest.mark.asyncio
async def test_file_backend_slugifies_subject_safely(tmp_path, monkeypatch):
    """Subject becomes part of the filename — strip anything that
    isn't `[A-Za-z0-9_-]` so weird subjects don't break the path on
    case-sensitive filesystems. Empty-after-strip falls back to
    `email`."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.framework.email.sender.settings.EMAIL_BACKEND", "file")

    await send_email(
        to="x@example.com",
        subject="!!! ;;;",
        html="<p/>",
        text="t",
    )

    files = list(Path(".mail").glob("*.eml"))
    assert len(files) == 1
    # Filename ends in `-email.eml` (the fallback slug) — pin this so
    # a future regex tweak that produces an empty slug doesn't silently
    # write a file with a dangling trailing dash.
    assert files[0].name.endswith("-email.eml")


@pytest.mark.asyncio
async def test_resend_backend_requires_api_key(monkeypatch):
    """Setting `EMAIL_BACKEND=resend` without `RESEND_API_KEY` is a
    misconfiguration we want to surface loudly — better an exception
    at first send than a silent no-op that drops verification mails."""
    monkeypatch.setattr("src.framework.email.sender.settings.EMAIL_BACKEND", "resend")
    monkeypatch.setattr("src.framework.email.sender.settings.RESEND_API_KEY", None)

    with pytest.raises(RuntimeError, match="RESEND_API_KEY"):
        await send_email(to="x@example.com", subject="s", html="h", text="t")


@pytest.mark.asyncio
async def test_resend_backend_calls_resend_sdk(monkeypatch):
    """When configured, the resend backend hands the message off to
    `resend.Emails.send` with the canonical payload shape (from, to,
    subject, html, text). Mock the import so CI never touches the
    network."""
    monkeypatch.setattr("src.framework.email.sender.settings.EMAIL_BACKEND", "resend")
    monkeypatch.setattr(
        "src.framework.email.sender.settings.RESEND_API_KEY", "test-key"
    )
    monkeypatch.setattr(
        "src.framework.email.sender.settings.EMAIL_FROM", "no-reply@example.com"
    )

    fake_resend = type(sys)("resend")
    fake_resend.api_key = None
    fake_resend.Emails = type(sys)("Emails")
    send_mock = AsyncMock()
    # Resend's send() is sync — `asyncio.to_thread` will await its
    # return — so the mock can also be sync. Use a plain Mock here
    # to mirror the SDK's actual call shape.
    from unittest.mock import Mock

    send_mock = Mock(return_value={"id": "msg_123"})
    fake_resend.Emails.send = send_mock

    with patch.dict(sys.modules, {"resend": fake_resend}):
        await send_email(
            to="alice@example.com",
            subject="Verify",
            html="<p>link</p>",
            text="link",
        )

    assert send_mock.call_count == 1
    payload = send_mock.call_args[0][0]
    assert payload == {
        "from": "no-reply@example.com",
        "to": ["alice@example.com"],
        "subject": "Verify",
        "html": "<p>link</p>",
        "text": "link",
    }
    assert fake_resend.api_key == "test-key"


@pytest.mark.asyncio
async def test_console_backend_includes_reply_to_when_set(capsys, monkeypatch):
    """`reply_to` is the conversation-routing knob for sender-to-poster
    flows (post messages) — the recipient's "Reply" should land in the
    sender's inbox, not the `EMAIL_FROM` no-reply mailbox. The console
    backend surfaces it as a `Reply-To:` line so dev sends visibly carry
    the header."""
    monkeypatch.setattr("src.framework.email.sender.settings.EMAIL_BACKEND", "console")
    monkeypatch.setattr(
        "src.framework.email.sender.settings.EMAIL_FROM", "no-reply@example.com"
    )

    await send_email(
        to="alice@example.com",
        subject="Hello",
        html="<p>Hi</p>",
        text="Hi",
        reply_to="bob@example.com",
    )

    err = capsys.readouterr().err
    assert "Reply-To: bob@example.com" in err


@pytest.mark.asyncio
async def test_file_backend_includes_reply_to_when_set(tmp_path, monkeypatch):
    """The `.eml`-shaped file emits a `Reply-To:` header — same rule
    as the console backend, but on disk so the dev can inspect the
    saved headers."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.framework.email.sender.settings.EMAIL_BACKEND", "file")
    monkeypatch.setattr(
        "src.framework.email.sender.settings.EMAIL_FROM", "no-reply@example.com"
    )

    await send_email(
        to="poster@example.com",
        subject="New message",
        html="<p>HTML</p>",
        text="Plain",
        reply_to="sender@example.com",
    )

    files = list(Path(".mail").glob("*.eml"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert "Reply-To: sender@example.com" in body


@pytest.mark.asyncio
async def test_resend_backend_forwards_reply_to(monkeypatch):
    """When set, `reply_to` lands in the Resend payload as a single
    string (Resend accepts string-or-list; we pass a string to match
    the public surface's single-address shape)."""
    monkeypatch.setattr("src.framework.email.sender.settings.EMAIL_BACKEND", "resend")
    monkeypatch.setattr(
        "src.framework.email.sender.settings.RESEND_API_KEY", "test-key"
    )
    monkeypatch.setattr(
        "src.framework.email.sender.settings.EMAIL_FROM", "no-reply@example.com"
    )

    fake_resend = type(sys)("resend")
    fake_resend.api_key = None
    fake_resend.Emails = type(sys)("Emails")
    from unittest.mock import Mock

    send_mock = Mock(return_value={"id": "msg_123"})
    fake_resend.Emails.send = send_mock

    with patch.dict(sys.modules, {"resend": fake_resend}):
        await send_email(
            to="poster@example.com",
            subject="New message",
            html="<p>m</p>",
            text="m",
            reply_to="sender@example.com",
        )

    payload = send_mock.call_args[0][0]
    assert payload["reply_to"] == "sender@example.com"


@pytest.mark.asyncio
async def test_resend_backend_omits_reply_to_when_unset(monkeypatch):
    """The default-None case must NOT add a `reply_to` key to the
    Resend payload — pinning this prevents an `{"reply_to": None}`
    regression that some SDK versions would forward as a literal
    `null` header."""
    monkeypatch.setattr("src.framework.email.sender.settings.EMAIL_BACKEND", "resend")
    monkeypatch.setattr(
        "src.framework.email.sender.settings.RESEND_API_KEY", "test-key"
    )
    monkeypatch.setattr(
        "src.framework.email.sender.settings.EMAIL_FROM", "no-reply@example.com"
    )

    fake_resend = type(sys)("resend")
    fake_resend.api_key = None
    fake_resend.Emails = type(sys)("Emails")
    from unittest.mock import Mock

    send_mock = Mock(return_value={"id": "msg_123"})
    fake_resend.Emails.send = send_mock

    with patch.dict(sys.modules, {"resend": fake_resend}):
        await send_email(to="x@example.com", subject="s", html="h", text="t")

    payload = send_mock.call_args[0][0]
    assert "reply_to" not in payload


@pytest.mark.asyncio
async def test_unknown_backend_raises(monkeypatch):
    """An unknown `EMAIL_BACKEND` value is a config typo — better to
    fail fast at first send than swallow it and lose mail."""
    monkeypatch.setattr(
        "src.framework.email.sender.settings.EMAIL_BACKEND", "carrier-pigeon"
    )

    with pytest.raises(ValueError, match="Unknown EMAIL_BACKEND"):
        await send_email(to="x@example.com", subject="s", html="h", text="t")
