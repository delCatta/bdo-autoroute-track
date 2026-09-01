"""The auto-route marker, and finding it on screen.

The marker follows a world position, so it slides around as the camera turns.
Its icon is matched across the whole frame and the digits are read from a box
placed relative to wherever the icon turned up. See HANDOFF.md sections 3 and 6.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

ICON_CLEARANCE_PX = 3


class MarkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    width: int
    height: int

    @property
    def empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    @property
    def origin(self) -> tuple[int, int]:
        return self.left, self.top

    def clamped_to(self, size: tuple[int, int]) -> "Box":
        width, height = size
        left, top = max(0, self.left), max(0, self.top)
        right, bottom = min(width, self.left + self.width), min(height, self.top + self.height)
        return Box(left, top, max(0, right - left), max(0, bottom - top))

    def crop(self, image: Image.Image) -> Image.Image:
        return image.crop((self.left, self.top, self.left + self.width, self.top + self.height))

    def as_list(self) -> list[int]:
        return [self.left, self.top, self.width, self.height]


@dataclass(frozen=True)
class Sighting:
    """Where the marker was found, and where its digits are."""

    confidence: float
    icon: Box
    digits: Box

    @property
    def readable(self) -> bool:
        """False when the marker sits so near an edge the digits are off screen."""
        return not self.digits.empty


@dataclass(frozen=True)
class Offset:
    """The digits box, expressed relative to the icon's top-left corner."""

    left: int
    top: int
    width: int
    height: int

    @classmethod
    def between(cls, digits: Box, icon: Box, *, left_slack: float = 2.0) -> "Offset":
        """Derive the offset from one calibrated pair of boxes.

        The box grows leftward by `left_slack` times the calibrated width so a
        longer number still fits, and rightward to just short of the icon: the
        gap between digits and icon shrinks as the number grows, and preserving
        the calibrated gap once clipped 14000 into 1400.
        """
        slack = int(round(digits.width * left_slack))
        left = (digits.left - slack) - icon.left
        width = max(digits.width + slack, -ICON_CLEARANCE_PX - left)
        padding = max(2, digits.height // 6)
        return cls(
            left=left,
            top=(digits.top - padding) - icon.top,
            width=width,
            height=digits.height + 2 * padding,
        )

    def scaled(self, factor: float) -> "Offset":
        return Offset(*(round(value * factor) for value in self.as_tuple()))

    def applied_to(self, icon: Box) -> Box:
        return Box(icon.left + self.left, icon.top + self.top, self.width, self.height)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height


class Marker:
    """The route icon, and the digits that sit beside it."""

    def __init__(
        self,
        icon: Image.Image,
        offset: Offset,
        *,
        match_threshold: float = 0.85,
        scale: float = 1.0,
    ) -> None:
        if icon.width < 3 or icon.height < 3:
            raise MarkerError("The icon template is too small to match reliably.")

        if scale != 1.0:
            icon = icon.resize(
                (max(3, round(icon.width * scale)), max(3, round(icon.height * scale))),
                Image.LANCZOS,
            )
            offset = offset.scaled(scale)

        self._threshold = match_threshold
        self._offset = offset
        self._icon = _as_cv(icon)
        self._size = (icon.width, icon.height)

    @property
    def icon_size(self) -> tuple[int, int]:
        return self._size

    def sighting(self, frame: Image.Image) -> Sighting | None:
        """Search the whole frame. None when nothing matched well enough."""
        confidence, position = self._best_match(frame)
        if confidence < self._threshold:
            return None
        icon = Box(position[0], position[1], *self._size)
        return Sighting(
            confidence=confidence,
            icon=icon,
            digits=self._offset.applied_to(icon).clamped_to(frame.size),
        )

    def confidence_in(self, frame: Image.Image) -> float:
        """The best score anywhere, ignoring the threshold.

        Used at calibration to measure the scenery noise floor, which a
        threshold has to sit clearly above.
        """
        return self._best_match(frame)[0]

    def _best_match(self, frame: Image.Image) -> tuple[float, tuple[int, int]]:
        haystack = _as_cv(frame)
        width, height = self._size
        if haystack.shape[0] < height or haystack.shape[1] < width:
            raise MarkerError("The frame is smaller than the icon template.")
        scores = cv2.matchTemplate(haystack, self._icon, cv2.TM_CCOEFF_NORMED)
        _, best, _, position = cv2.minMaxLoc(scores)
        return float(best), (int(position[0]), int(position[1]))


def _as_cv(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
