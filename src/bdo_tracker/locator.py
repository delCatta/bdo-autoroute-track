"""Find the route marker on screen and derive the digits box from it.

The remaining-distance marker is anchored to a world position, so it slides
around the screen as the camera moves. A fixed crop box therefore cannot work.

Instead the distinctive route icon is template-matched across the whole frame,
and the digits are read from a box positioned relative to wherever the icon was
found. The digits sit to the LEFT of the icon, so the box extends leftward with
slack for longer distances (a five-digit reading is wider than "600").
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


class LocatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class Match:
    """Where the icon was found, and the digits box implied by it."""

    confidence: float
    icon_box: tuple[int, int, int, int]    # left, top, width, height
    digits_box: tuple[int, int, int, int]  # left, top, width, height, clamped to frame

    @property
    def has_digits(self) -> bool:
        """False when the marker sits so near an edge that the digits are off-screen.

        Distinct from the icon not being found at all: one means the camera is
        pointed away, the other means it is pointed almost far enough.
        """
        return self.digits_box[2] > 0 and self.digits_box[3] > 0


def _to_cv(image: Image.Image) -> np.ndarray:
    """PIL RGB -> OpenCV BGR."""
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


class MarkerLocator:
    """Template-matches the route icon and returns the digits box beside it.

    `digits_offset` is the digits box expressed relative to the icon's top-left
    corner, as recorded during calibration.
    """

    def __init__(
        self,
        template: Image.Image,
        digits_offset: tuple[int, int, int, int],
        *,
        match_threshold: float = 0.7,
        scale: float = 1.0,
    ) -> None:
        if template.width < 3 or template.height < 3:
            raise LocatorError("The icon template is too small to match reliably.")
        self._threshold = match_threshold
        self._scale = scale

        if scale != 1.0:
            new_size = (
                max(3, round(template.width * scale)),
                max(3, round(template.height * scale)),
            )
            template = template.resize(new_size, Image.LANCZOS)
            digits_offset = tuple(round(v * scale) for v in digits_offset)  # type: ignore[assignment]

        self._template = _to_cv(template)
        self._t_h, self._t_w = self._template.shape[:2]
        self._digits_offset = digits_offset

    @property
    def template_size(self) -> tuple[int, int]:
        return self._t_w, self._t_h

    def best_confidence(self, frame: Image.Image) -> float:
        """Highest template-match score anywhere in the frame, ignoring the threshold.

        Used during calibration to measure the noise floor: the best score on a
        frame with the marker removed. A threshold must sit clearly above that,
        or random scenery will be mistaken for the marker and a fabricated
        distance reported.
        """
        haystack = _to_cv(frame)
        if haystack.shape[0] < self._t_h or haystack.shape[1] < self._t_w:
            raise LocatorError("The frame is smaller than the icon template.")
        result = cv2.matchTemplate(haystack, self._template, cv2.TM_CCOEFF_NORMED)
        return float(cv2.minMaxLoc(result)[1])

    def locate(self, frame: Image.Image) -> Match | None:
        """Search the whole frame for the icon. None if nothing matched well enough."""
        haystack = _to_cv(frame)
        if haystack.shape[0] < self._t_h or haystack.shape[1] < self._t_w:
            raise LocatorError("The frame is smaller than the icon template.")

        result = cv2.matchTemplate(haystack, self._template, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        if max_val < self._threshold:
            return None

        icon_left, icon_top = int(max_loc[0]), int(max_loc[1])
        dx, dy, dw, dh = self._digits_offset

        left = icon_left + dx
        top = icon_top + dy
        # Clamp to the frame so a marker near an edge still yields a valid crop.
        frame_h, frame_w = haystack.shape[:2]
        left_c = max(0, left)
        top_c = max(0, top)
        right_c = min(frame_w, left + dw)
        bottom_c = min(frame_h, top + dh)
        # An empty box means the digits fell off-screen. Still report the
        # sighting, so the caller can say so rather than "marker not found".
        width_c = max(0, right_c - left_c)
        height_c = max(0, bottom_c - top_c)

        return Match(
            confidence=float(max_val),
            icon_box=(icon_left, icon_top, self._t_w, self._t_h),
            digits_box=(left_c, top_c, width_c, height_c),
        )

    def crop_digits(self, frame: Image.Image, match: Match) -> Image.Image:
        left, top, width, height = match.digits_box
        return frame.crop((left, top, left + width, top + height))


# How close to the icon's left edge the digits box is allowed to reach. Small,
# because the gap between the digits and the icon shrinks as the number grows.
ICON_CLEARANCE_PX = 3


def digits_offset_from_boxes(
    digits_box: tuple[int, int, int, int],
    icon_box: tuple[int, int, int, int],
    *,
    left_slack: float = 2.0,
) -> tuple[int, int, int, int]:
    """Express the digits box relative to the icon, sized for any number length.

    The box grows in BOTH directions from what was calibrated:

    - Leftward by `left_slack` times the observed digit width, so calibrating on
      "600" still captures "12345".
    - Rightward to just short of the icon. The whitespace between the digits and
      the icon is NOT constant: calibrating on "600" showed a 17px gap, but a
      live five-digit reading of 14000 sat about 8px from the icon and had its
      last digit clipped, turning 14000 into 1400. Preserving the calibrated gap
      is therefore wrong; hugging the icon is right.
    """
    d_left, d_top, d_w, d_h = digits_box
    i_left, i_top, _i_w, _i_h = icon_box

    extra = int(round(d_w * left_slack))
    left_rel = (d_left - extra) - i_left
    right_rel = -ICON_CLEARANCE_PX
    # Never end up narrower than what was actually calibrated.
    width = max(d_w + extra, right_rel - left_rel)

    # A little vertical padding absorbs glyphs that sit slightly higher or lower.
    pad_y = max(2, d_h // 6)
    return (
        left_rel,
        (d_top - pad_y) - i_top,
        width,
        d_h + 2 * pad_y,
    )
