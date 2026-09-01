"""Delivery of alerts to a Discord webhook.

Knows about HTTP and Discord's payload shape, and nothing about routes.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass

import requests
from PIL import Image

from .alerts import Alert
from .vault import scrubbed

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20
JPEG_QUALITY = 80
MAX_SCREENSHOT_WIDTH = 1280


class NotifyError(RuntimeError):
    pass


def encoded(image: Image.Image, max_width: int = MAX_SCREENSHOT_WIDTH) -> bytes:
    """Downscaled JPEG bytes, so uploads stay small and fast."""
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, round(image.height * ratio))), Image.LANCZOS)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


@dataclass
class Discord:
    """One Discord webhook."""

    webhook_url: str
    mention: str = ""
    name: str = "discord"

    def __post_init__(self) -> None:
        if not self.webhook_url:
            raise NotifyError(
                "notify.discord_webhook_url is empty in config.toml. Create one "
                "under Channel > Edit Channel > Integrations > Webhooks."
            )
        self._session = requests.Session()

    def deliver(self, alert: Alert) -> bool:
        """Post one alert. True on success.

        A failed alert must not take the monitor down with it, so problems are
        logged and reported by return value rather than raised.
        """
        try:
            response = self._post(self._payload(alert), self._attachment(alert))
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            log.warning("Discord notification failed: %s", self._safely(exc))
            return False

    def _safely(self, exc: Exception) -> str:
        """What went wrong, without the webhook token in it."""
        return scrubbed(f"{exc.__class__.__name__}: {exc}", self.webhook_url)

    def _payload(self, alert: Alert) -> dict[str, object]:
        embed: dict[str, object] = {
            "title": alert.headline,
            "description": alert.body,
            "color": alert.colour,
            "fields": [
                {"name": name, "value": value, "inline": True}
                for name, value in alert.stamped_details.items()
            ],
        }
        if alert.screenshot is not None:
            embed["image"] = {"url": "attachment://frame.jpg"}

        payload: dict[str, object] = {"embeds": [embed]}
        if alert.urgent and self.mention:
            payload["content"] = self.mention
        return payload

    @staticmethod
    def _attachment(alert: Alert) -> dict[str, tuple[str, bytes, str]] | None:
        shot = alert.thumbnail(MAX_SCREENSHOT_WIDTH)
        if shot is None:
            return None
        return {"files[0]": ("frame.jpg", encoded(shot), "image/jpeg")}

    def _post(self, payload: dict[str, object], files: dict | None) -> requests.Response:
        if files:
            return self._session.post(
                self.webhook_url,
                data={"payload_json": json.dumps(payload)},
                files=files,
                timeout=TIMEOUT_SECONDS,
            )
        return self._session.post(self.webhook_url, json=payload, timeout=TIMEOUT_SECONDS)
