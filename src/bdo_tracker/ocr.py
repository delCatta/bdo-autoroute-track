"""Read the remaining-distance number out of a cropped game region.

The readout is light stylised digits on a dark, slightly textured background,
with a glowing route icon beside it. The pipeline is therefore:

    upscale -> threshold on brightness -> invert -> pad -> OCR -> parse digits

Thresholding is done on the max colour channel rather than luminance, because
the game turns the text red near the destination and red is dim by luminance.
The icon is excluded by the calibrated crop; as a backstop the parser takes the
numeric run with the most digits, since stray fragments are short.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from PIL import Image

# A number with optional thousands separators, plus an optional unit.
# Matches "3970", "3,970", "1.2km", "450 m".
#
# The separator class includes apostrophes because OCR renders the game's
# thousands separator that way: a live frame reading 1169 m came back as
# "11'69", which a comma-only pattern split into "11" and "69".
_SEPARATORS = ".,'`’´"
_NUMBER_RE = re.compile(rf"(\d[\d{re.escape(_SEPARATORS)}]*)\s*(km|m)?", re.IGNORECASE)
_STRIP_SEPARATORS = re.compile(rf"[{re.escape(_SEPARATORS)}]")


class OcrError(RuntimeError):
    pass


@dataclass(frozen=True)
class Reading:
    """One attempt at reading the distance readout."""

    meters: float | None
    raw_text: str
    # Fraction of the glyph pixels that are red. The game turns the distance
    # text red once you are close, so this is the game's own near-arrival hint.
    red_ratio: float = 0.0

    @property
    def ok(self) -> bool:
        return self.meters is not None

    @property
    def near_indicator(self) -> bool:
        """True when the readout has gone red."""
        return self.red_ratio >= RED_RATIO_THRESHOLD


# A glyph pixel counts as red when R leads G and B by this much (0-255).
RED_DOMINANCE = 45
# ...and the readout counts as "gone red" once this fraction of glyphs qualify.
RED_RATIO_THRESHOLD = 0.5


def red_ratio(image: Image.Image, brightness_threshold: int) -> float:
    """Fraction of the crop's bright glyph pixels that are red-dominant."""
    rgb = np.asarray(image.convert("RGB")).astype(int)
    glyphs = rgb.max(axis=2) >= brightness_threshold
    total = int(glyphs.sum())
    if total == 0:
        return 0.0
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    is_red = (red - np.maximum(green, blue)) >= RED_DOMINANCE
    return float((is_red & glyphs).sum()) / total


def value_channel(image: Image.Image) -> np.ndarray:
    """Per-pixel max of R, G and B - the HSV "value" channel.

    Deliberately NOT luminance. The game turns the distance text RED as a
    near-arrival indicator, and red has a luminance around 105, which would
    fall below any threshold that keeps white text at 232. Their max channel,
    though, is ~230 for both. Thresholding on value keeps white and red
    digits alike, so the reader does not go blind exactly when it matters.
    """
    return np.asarray(image.convert("RGB")).max(axis=2)


def preprocess(image: Image.Image, upscale: int, brightness_threshold: int) -> Image.Image:
    """Turn a game crop into high-contrast dark-text-on-white for the OCR engine."""
    rgb = image.convert("RGB")
    if upscale > 1:
        rgb = rgb.resize(
            (rgb.width * upscale, rgb.height * upscale), resample=Image.LANCZOS
        )

    arr = value_channel(rgb)
    # Bright pixels are the glyphs. Invert so glyphs end up black on white.
    binary = np.where(arr >= brightness_threshold, 0, 255).astype(np.uint8)

    out = Image.fromarray(binary, mode="L")
    # A quiet margin around the text measurably improves both backends.
    padded = Image.new("L", (out.width + 24, out.height + 24), color=255)
    padded.paste(out, (12, 12))
    return padded


def parse_distance(
    text: str, min_valid: float, max_valid: float, *, prefer: str = "longest"
) -> float | None:
    """Pull a plausible distance out of raw OCR text. Returns metres, or None.

    The crop is anchored to the route icon and extends leftward with slack, so
    stray fragments can appear alongside the real number. A live frame produced
    "11'69 9": the reading was 1169, but a right-most rule picked the stray "9"
    and would have declared a false arrival.

    The default rule is therefore to take the candidate with the MOST digits,
    since noise fragments are short and the distance is the dominant number.
    Ties break toward the right, nearest the icon.
    """
    candidates: list[tuple[int, int, float]] = []  # digit count, position, value
    for match in _NUMBER_RE.finditer(text):
        digits, unit = match.group(1), match.group(2)
        # Separators are decoration in this readout ("3,970"), not decimals,
        # except when a unit of km makes a real decimal likely ("1.2km").
        if unit and unit.lower() == "km":
            cleaned = _STRIP_SEPARATORS.sub("", digits.replace(".", "\x00")).replace("\x00", ".")
            try:
                value = float(cleaned) * 1000.0
            except ValueError:
                continue
            digit_count = sum(c.isdigit() for c in cleaned)
        else:
            cleaned = _STRIP_SEPARATORS.sub("", digits)
            if not cleaned:
                continue
            try:
                value = float(cleaned)
            except ValueError:
                continue
            digit_count = len(cleaned)
        if min_valid <= value <= max_valid:
            candidates.append((digit_count, match.start(), value))

    if not candidates:
        return None
    if prefer == "left":
        return candidates[0][2]
    if prefer == "right":
        return candidates[-1][2]
    # "longest": most digits wins, then the right-most of those.
    return max(candidates, key=lambda c: (c[0], c[1]))[2]


class OcrBackend(ABC):
    """Reads text from a preprocessed image."""

    @abstractmethod
    def read_text(self, image: Image.Image) -> str: ...


class RapidOcrBackend(OcrBackend):
    """ONNX-based OCR. Pure pip install, no external binary needed on Windows."""

    def __init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover - install-time failure
            raise OcrError(
                "rapidocr-onnxruntime is not installed. "
                "Run the setup script, or set ocr.backend = 'tesseract' in config.toml."
            ) from exc
        self._engine = RapidOCR()

    def read_text(self, image: Image.Image) -> str:
        result, _elapsed = self._engine(np.asarray(image.convert("RGB")))
        if not result:
            return ""
        # Sort detections left-to-right so the digits precede any stray glyph
        # picked up from the route icon.
        def _x_of(det: object) -> float:
            box = det[0]  # type: ignore[index]
            return min(float(pt[0]) for pt in box)

        try:
            ordered = sorted(result, key=_x_of)
        except (TypeError, IndexError, ValueError):
            ordered = list(result)
        return " ".join(str(det[1]) for det in ordered)


class TesseractBackend(OcrBackend):
    """Classic Tesseract. Needs the Tesseract binary installed separately."""

    # Single text line, digits and distance units only.
    _CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789.,kmKM"

    def __init__(self) -> None:
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover - install-time failure
            raise OcrError(
                "pytesseract is not installed. "
                "Run `pip install pytesseract` and install the Tesseract binary, "
                "or set ocr.backend = 'rapidocr' in config.toml."
            ) from exc
        self._pytesseract = pytesseract

    def read_text(self, image: Image.Image) -> str:
        return self._pytesseract.image_to_string(image, config=self._CONFIG)


def make_backend(name: str) -> OcrBackend:
    if name == "rapidocr":
        return RapidOcrBackend()
    if name == "tesseract":
        return TesseractBackend()
    raise OcrError(f"Unknown OCR backend {name!r}.")


class DistanceReader:
    """Preprocess a crop, OCR it, and parse out a distance in metres."""

    def __init__(
        self,
        backend: OcrBackend,
        *,
        upscale: int,
        brightness_threshold: int,
        min_valid_m: float,
        max_valid_m: float,
        prefer: str = "longest",
    ) -> None:
        self._backend = backend
        self._upscale = upscale
        self._brightness_threshold = brightness_threshold
        self._min_valid = min_valid_m
        self._max_valid = max_valid_m
        self._prefer = prefer

    def prepare(self, crop: Image.Image) -> Image.Image:
        """Expose the preprocessed image so `calibrate` can show what OCR sees."""
        return preprocess(crop, self._upscale, self._brightness_threshold)

    def read(self, crop: Image.Image) -> Reading:
        redness = red_ratio(crop, self._brightness_threshold)
        prepared = self.prepare(crop)
        try:
            text = self._backend.read_text(prepared)
        except Exception as exc:  # a bad frame must not kill the monitor loop
            return Reading(meters=None, raw_text=f"<ocr error: {exc}>", red_ratio=redness)
        cleaned = " ".join(text.split())
        return Reading(
            meters=parse_distance(
                cleaned, self._min_valid, self._max_valid, prefer=self._prefer
            ),
            raw_text=cleaned,
            red_ratio=redness,
        )
