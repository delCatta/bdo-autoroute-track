"""Reading the remaining-distance number off a crop of the marker.

Thresholding uses the max colour channel rather than luminance: the game turns
the text red near the destination, and red is dim by luminance. See .claude/CONTEXT.md
sections 3 and 5.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from PIL import Image

SEPARATORS = ".,'`’´"
NUMBER = re.compile(rf"(\d[\d{re.escape(SEPARATORS)}]*)\s*(km|m)?", re.IGNORECASE)
STRIP = re.compile(rf"[{re.escape(SEPARATORS)}]")

RED_DOMINANCE = 45
RED_RATIO = 0.5
GLYPH_PADDING = 12


class OcrError(RuntimeError):
    pass


@dataclass(frozen=True)
class Reading:
    """One attempt at reading the number."""

    meters: float | None
    raw_text: str
    red_ratio: float = 0.0

    @property
    def understood(self) -> bool:
        return self.meters is not None

    @property
    def near_indicator(self) -> bool:
        """The game turned the readout red, which it does only when you are close."""
        return self.red_ratio >= RED_RATIO


class Glyphs:
    """The bright pixels of a crop, isolated from the background behind them."""

    def __init__(self, crop: Image.Image, *, threshold: int, upscale: int = 1) -> None:
        self._crop = crop
        self._threshold = threshold
        self._upscale = upscale

    @property
    def redness(self) -> float:
        """Fraction of glyph pixels that are red-dominant."""
        pixels = np.asarray(self._crop.convert("RGB")).astype(int)
        lit = pixels.max(axis=2) >= self._threshold
        if not lit.any():
            return 0.0
        red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        dominant = (red - np.maximum(green, blue)) >= RED_DOMINANCE
        return float((dominant & lit).sum()) / float(lit.sum())

    @property
    def stencil(self) -> Image.Image:
        """High-contrast black-on-white, which is what OCR engines want."""
        image = self._crop.convert("RGB")
        if self._upscale > 1:
            image = image.resize(
                (image.width * self._upscale, image.height * self._upscale), Image.LANCZOS
            )
        lit = value_channel(image) >= self._threshold
        inked = Image.fromarray(np.where(lit, 0, 255).astype(np.uint8), mode="L")

        padded = Image.new(
            "L", (inked.width + 2 * GLYPH_PADDING, inked.height + 2 * GLYPH_PADDING), 255
        )
        padded.paste(inked, (GLYPH_PADDING, GLYPH_PADDING))
        return padded


def value_channel(image: Image.Image) -> np.ndarray:
    """Per-pixel max of R, G and B. Deliberately not luminance."""
    return np.asarray(image.convert("RGB")).max(axis=2)


def distance_in(text: str, *, floor: float, ceiling: float, prefer: str = "longest") -> float | None:
    """The distance hiding in raw OCR text, in metres.

    Longest run wins: stray fragments are short, the distance is the dominant
    number, and a right-most rule once picked a stray "9" out of "11'69 9".
    """
    candidates: list[tuple[int, int, float]] = []
    for match in NUMBER.finditer(text):
        digits, unit = match.group(1), match.group(2)
        value = _kilometres(digits) if _is_km(unit) else _metres(digits)
        if value is None or not floor <= value <= ceiling:
            continue
        candidates.append((_digit_count(digits), match.start(), value))

    if not candidates:
        return None
    if prefer == "left":
        return candidates[0][2]
    if prefer == "right":
        return candidates[-1][2]
    return max(candidates, key=lambda c: (c[0], c[1]))[2]


def _is_km(unit: str | None) -> bool:
    return bool(unit) and unit.lower() == "km"


def _metres(digits: str) -> float | None:
    cleaned = STRIP.sub("", digits)
    return float(cleaned) if cleaned else None


def _kilometres(digits: str) -> float | None:
    cleaned = STRIP.sub("", digits.replace(".", "\x00")).replace("\x00", ".")
    try:
        return float(cleaned) * 1000.0
    except ValueError:
        return None


def _digit_count(digits: str) -> int:
    return sum(character.isdigit() for character in digits)


class Engine(ABC):
    """Something that turns a stencil into text."""

    @abstractmethod
    def text_in(self, stencil: Image.Image) -> str: ...


class RapidOcr(Engine):
    """ONNX-based OCR. Pure pip install, no external binary on Windows."""

    def __init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise OcrError(
                "rapidocr-onnxruntime is not installed. Run setup.ps1 again, "
                'or set ocr.backend = "tesseract".'
            ) from exc
        self._engine = RapidOCR()

    def text_in(self, stencil: Image.Image) -> str:
        found, _elapsed = self._engine(np.asarray(stencil.convert("RGB")))
        if not found:
            return ""
        return " ".join(str(detection[1]) for detection in _left_to_right(found))


class Tesseract(Engine):
    """Classic Tesseract. Needs the binary installed separately."""

    CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789.,kmKM"

    def __init__(self) -> None:
        try:
            import pytesseract
        except ImportError as exc:
            raise OcrError(
                "pytesseract is not installed. Install it and the Tesseract "
                'binary, or set ocr.backend = "rapidocr".'
            ) from exc
        self._pytesseract = pytesseract

    def text_in(self, stencil: Image.Image) -> str:
        return self._pytesseract.image_to_string(stencil, config=self.CONFIG)


def engine_for(name: str) -> Engine:
    if name == "rapidocr":
        return RapidOcr()
    if name == "tesseract":
        return Tesseract()
    raise OcrError(f"Unknown OCR backend {name!r}.")


def _left_to_right(detections: list) -> list:
    try:
        return sorted(detections, key=lambda d: min(float(p[0]) for p in d[0]))
    except (TypeError, IndexError, ValueError):
        return list(detections)


class Readout:
    """The distance number as the game draws it."""

    def __init__(
        self,
        engine: Engine,
        *,
        upscale: int,
        brightness_threshold: int,
        floor_m: float,
        ceiling_m: float,
    ) -> None:
        self._engine = engine
        self._upscale = upscale
        self._threshold = brightness_threshold
        self._floor = floor_m
        self._ceiling = ceiling_m

    def stencil(self, crop: Image.Image) -> Image.Image:
        """What the OCR engine actually sees. Written out during calibration."""
        return self._glyphs(crop).stencil

    def reading(self, crop: Image.Image) -> Reading:
        glyphs = self._glyphs(crop)
        redness = glyphs.redness
        try:
            text = self._engine.text_in(glyphs.stencil)
        except Exception as exc:
            return Reading(None, f"<ocr error: {exc}>", redness)

        tidied = " ".join(text.split())
        return Reading(
            meters=distance_in(tidied, floor=self._floor, ceiling=self._ceiling),
            raw_text=tidied,
            red_ratio=redness,
        )

    def _glyphs(self, crop: Image.Image) -> Glyphs:
        return Glyphs(crop, threshold=self._threshold, upscale=self._upscale)
