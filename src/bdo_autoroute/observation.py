"""What one look at the screen saw."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .marker import Sighting
from .readout import Reading

UNPARSED = "unparsed"
NO_MARKER = "no_marker"
LOW_CONFIDENCE = "low_confidence"
RED = "red"
ORDINARY = "ordinary"

CATEGORIES = (UNPARSED, NO_MARKER, LOW_CONFIDENCE, RED, ORDINARY)

LOW_CONFIDENCE_MARGIN = 0.05


@dataclass(frozen=True)
class Observation:
    """One poll: the frame, where the marker was, and what it said."""

    frame: Image.Image
    sighting: Sighting | None = None
    reading: Reading | None = None

    @property
    def seen(self) -> bool:
        return self.sighting is not None

    @property
    def readable(self) -> bool:
        return self.sighting is not None and self.sighting.readable

    @property
    def distance(self) -> float | None:
        return self.reading.meters if self.reading else None

    @property
    def near_indicator(self) -> bool:
        return bool(self.reading and self.reading.near_indicator)

    @property
    def confidence(self) -> float:
        return self.sighting.confidence if self.sighting else 0.0

    @property
    def redness(self) -> float:
        return self.reading.red_ratio if self.reading else 0.0

    @property
    def raw_text(self) -> str:
        if self.reading is not None:
            return self.reading.raw_text
        if self.sighting is None:
            return "<marker not found>"
        return "<marker at screen edge, digits off screen>"

    def category(self, match_threshold: float) -> str:
        """Which training bucket this poll belongs in, worst outcome winning."""
        if not self.seen:
            return NO_MARKER
        if not self.readable or self.distance is None:
            return UNPARSED
        if self.confidence < match_threshold + LOW_CONFIDENCE_MARGIN:
            return LOW_CONFIDENCE
        if self.near_indicator:
            return RED
        return ORDINARY

    def sample(self, category: str) -> Image.Image:
        """A missing marker only means anything as a whole frame."""
        if category == NO_MARKER or self.sighting is None or not self.sighting.readable:
            return self.frame
        return self.sighting.digits.crop(self.frame)

    def neighbourhood(self, margin: float) -> Image.Image | None:
        """The marker and a little context, for alerts that must not carry chat.

        A full game window shows whispers, guild chat, the character name and
        the marketplace. Fine in a private channel, a leak in a shared one.
        """
        if self.sighting is None:
            return None

        icon, digits = self.sighting.icon, self.sighting.digits
        left = min(icon.left, digits.left)
        top = min(icon.top, digits.top)
        right = max(icon.left + icon.width, digits.left + digits.width)
        bottom = max(icon.top + icon.height, digits.top + digits.height)

        pad_x = int((right - left) * margin)
        pad_y = int((bottom - top) * margin)
        return self.frame.crop(
            (
                max(0, left - pad_x),
                max(0, top - pad_y),
                min(self.frame.width, right + pad_x),
                min(self.frame.height, bottom + pad_y),
            )
        )

    def as_metadata(self, match_threshold: float) -> dict[str, object]:
        return {
            "raw_ocr": self.raw_text,
            "meters": self.distance,
            "red_ratio": round(self.redness, 3),
            "match_confidence": round(self.confidence, 4),
            "match_threshold": match_threshold,
            "icon_box": self.sighting.icon.as_list() if self.sighting else None,
            "digits_box": self.sighting.digits.as_list() if self.sighting else None,
        }
