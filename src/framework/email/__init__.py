"""Transactional email — provider-shaped transport.

Public surface:
    `send_email(to, subject, html, text)` — single async call. Dispatches
    to one of three backends keyed off `settings.EMAIL_BACKEND`:
      - `console` (default) prints to stdout. Dev-friendly; clickable
        links land in the terminal.
      - `file` writes timestamped files under `./.mail/` for HTML
        inspection.
      - `resend` calls the Resend HTTP API.

Callers don't import the backend; the dispatch is internal so swapping
providers later is a one-file edit. See `sender.py` for the rule.
"""

from src.framework.email.sender import send_email

__all__ = ["send_email"]
