"""The tray icon, drawn per state.

An icon that always looks the same wastes the only thing a tray icon is good
at: saying how things are without being opened. The hull takes the state's
colour, the same one the Discord embed uses, so the two never disagree.

Drawn rather than shipped: no game artwork is involved, and a colour variant
costs nothing.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .alerts import COLOURS
from .voyage import State

SIZE = 64
MUTED = (120, 124, 134)


def rgb(packed: int) -> tuple[int, int, int]:
    """0xRRGGBB as a tuple."""
    return (packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF


def boat(accent: tuple[int, int, int], size: int = SIZE) -> Image.Image:
    """A small boat whose hull carries the accent colour."""
    scale = size / 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def at(*points: float) -> list[float]:
        return [point * scale for point in points]

    draw.rounded_rectangle(at(8, 8, 248, 248), radius=int(48 * scale), fill=(24, 28, 38, 255))
    draw.polygon(
        [(132 * scale, 44 * scale), (132 * scale, 150 * scale), (206 * scale, 150 * scale)],
        fill=(236, 233, 224, 255),
    )
    draw.polygon(
        [(122 * scale, 60 * scale), (122 * scale, 150 * scale), (70 * scale, 150 * scale)],
        fill=(150, 158, 178, 255),
    )
    draw.rectangle(at(124, 40, 130, 152), fill=(236, 233, 224, 255))
    draw.polygon(
        [
            (48 * scale, 164 * scale),
            (208 * scale, 164 * scale),
            (180 * scale, 208 * scale),
            (76 * scale, 208 * scale),
        ],
        fill=(*accent, 255),
    )
    draw.rounded_rectangle(at(44, 218, 212, 228), radius=int(5 * scale), fill=(90, 120, 160, 255))
    return image


def for_state(state: State, *, muted: bool = False, size: int = SIZE) -> Image.Image:
    """The icon for a state, greyed out while notifications are muted."""
    accent = MUTED if muted else rgb(COLOURS.get(state, COLOURS[State.TRAVELLING]))
    return boat(accent, size)


def every_state(size: int = SIZE) -> dict[tuple[State, bool], Image.Image]:
    """Every icon the tray can need, drawn once up front."""
    return {
        (state, muted): for_state(state, muted=muted, size=size)
        for state in State
        for muted in (False, True)
    }
