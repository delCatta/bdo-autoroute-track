"""Deliver alerts to a Discord webhook, with an optional screenshot attached."""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass

import requests
from PIL import Image

log = logging.getLogger(__name__)

# Discord embed sidebar colours per state.
_COLOURS = {
    "ARRIVED": 0x2ECC71,      # green
    "STUCK": 0xE67E22,        # orange
    "SIGNAL_LOST": 0xE74C3C,  # red
    "SAILING": 0x3498DB,      # blue
    "STARTING": 0x95A5A6,     # grey
}

_TIMEOUT_SECONDS = 20
_JPEG_QUALITY = 80


class NotifyError(RuntimeError):
    pass


def encode_screenshot(image: Image.Image, max_width: int = 1280) -> bytes:
    """Downscale and JPEG-encode a frame so uploads stay small and fast."""
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, round(image.height * ratio))), Image.LANCZOS)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


@dataclass
class DiscordNotifier:
    webhook_url: str
    mention: str = ""

    def __post_init__(self) -> None:
        if not self.webhook_url:
            raise NotifyError(
                "notify.discord_webhook_url is empty in config.toml. "
                "Create one under Channel > Edit Channel > Integrations > Webhooks."
            )
        self._session = requests.Session()

    def send(
        self,
        *,
        title: str,
        description: str,
        state: str,
        fields: dict[str, str] | None = None,
        screenshot: Image.Image | None = None,
        ping: bool = False,
    ) -> bool:
        """Post one alert. Returns True on success; never raises on network failure.

        A failed alert must not take the monitor down with it, so problems are
        logged and reported by return value instead.
        """
        embed: dict[str, object] = {
            "title": title,
            "description": description,
            "color": _COLOURS.get(state, _COLOURS["SAILING"]),
        }
        if fields:
            embed["fields"] = [
                {"name": name, "value": value, "inline": True} for name, value in fields.items()
            ]

        payload: dict[str, object] = {"embeds": [embed]}
        if ping and self.mention:
            payload["content"] = self.mention

        files = None
        if screenshot is not None:
            embed["image"] = {"url": "attachment://frame.jpg"}
            files = {"files[0]": ("frame.jpg", encode_screenshot(screenshot), "image/jpeg")}

        try:
            if files:
                response = self._session.post(
                    self.webhook_url,
                    data={"payload_json": json.dumps(payload)},
                    files=files,
                    timeout=_TIMEOUT_SECONDS,
                )
            else:
                response = self._session.post(
                    self.webhook_url, json=payload, timeout=_TIMEOUT_SECONDS
                )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            log.warning("Discord notification failed: %s", exc)
            return False
