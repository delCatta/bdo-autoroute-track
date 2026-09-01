"""Keeping the webhook URL out of plain sight.

A Discord webhook URL is a bearer credential: anyone holding it can post to that
channel. Windows DPAPI encrypts it against the current user account, so the
stored form is useless on another machine or under another Windows user, and a
config.toml that gets zipped, synced or pasted somewhere carries nothing usable.

What this does NOT protect against: anything already running as you. DPAPI will
decrypt for any process with your credentials, this one included. It raises the
cost of a leaked file, not of a compromised account.
"""

from __future__ import annotations

import base64
import logging
import re

log = logging.getLogger(__name__)

PREFIX = "enc:"
DESCRIPTION = "bdo-autoroute-track webhook"

# The token is the last path segment of a webhook URL. Matched on the path
# rather than the whole URL because a connection error reports the path alone,
# with the host in a separate part of the message.
WEBHOOK_TOKEN = re.compile(r"(/api/webhooks/\d+/)[\w.-]+")


def available() -> bool:
    """True when DPAPI can be used at all."""
    try:
        import win32crypt  # noqa: F401
    except Exception:
        return False
    return True


def protected(secret: str) -> str:
    """The stored form of a secret: `enc:` plus a DPAPI blob, base64 encoded.

    Returns the secret unchanged if it is empty or already protected, or if
    DPAPI is unavailable, because a working plaintext config beats a broken one.
    """
    if not secret or secret.startswith(PREFIX):
        return secret

    try:
        import win32crypt

        blob = win32crypt.CryptProtectData(secret.encode("utf-8"), DESCRIPTION, None, None, None, 0)
        return PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception as exc:
        log.warning("Could not encrypt the secret (%s); storing it as it is.", exc)
        return secret


def revealed(stored: str) -> str:
    """The usable secret, whether it was stored encrypted or not."""
    if not stored or not stored.startswith(PREFIX):
        return stored

    try:
        import win32crypt

        blob = base64.b64decode(stored[len(PREFIX):])
        _description, secret = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return secret.decode("utf-8")
    except Exception as exc:
        log.error(
            "Could not decrypt the stored webhook (%s). It was encrypted for a "
            "different Windows user or machine; re-enter it in Settings.",
            exc,
        )
        return ""


def scrubbed(text: str, *secrets: str) -> str:
    """Text with any webhook token taken out, safe for a log or a dialog.

    `requests` puts the URL it was given into its exception messages, both as a
    full URL on an HTTP error and as a bare path on a connection error. Logging
    one raw wrote the live credential into logs/autoroute.log, which is the file
    CONTRIBUTING.md asks people to attach to an issue.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, masked(secret))
    return WEBHOOK_TOKEN.sub(r"\1(token)", text)


def masked(secret: str) -> str:
    """A form safe to show in a log or a screenshot."""
    if not secret:
        return "(not set)"
    if secret.startswith(PREFIX):
        return "(encrypted)"
    tail = secret[-6:] if len(secret) > 6 else ""
    return f"...{tail}"
