"""The game window, and the two ways of getting pixels out of it.

Read-only throughout: no memory reads, no injection, no synthesised input.
"""

from __future__ import annotations

import logging
import sys
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

import mss
import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

CAPTURE_TIMEOUT_SECONDS = 5.0
BLANK_LUMINANCE = 8


class CaptureError(RuntimeError):
    pass


class WindowMinimised(CaptureError):
    """Minimised or hidden, so there are no pixels to read. See .claude/CONTEXT.md, #6."""


def process_name(hwnd: int) -> str:
    """The executable owning a window, or "" if it cannot be read."""
    try:
        import win32api
        import win32con
        import win32process

        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        try:
            return win32process.GetModuleFileNameEx(handle, 0).rsplit("\\", 1)[-1]
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def blank(image: Image.Image) -> bool:
    """Essentially all black, as Fullscreen Exclusive mode produces."""
    return bool(np.asarray(image.convert("L")).max() <= BLANK_LUMINANCE)


@dataclass(frozen=True)
class Window:
    """A game window: where it is, and whether it can be seen."""

    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int
    frame_left: int
    frame_top: int
    visible: bool = True
    process: str = ""

    @property
    def offset(self) -> tuple[int, int]:
        """Where the drawable area starts inside the window frame."""
        return self.left - self.frame_left, self.top - self.frame_top

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    @classmethod
    def all(cls, *, include_hidden: bool = False) -> list[tuple[int, str]]:
        _require_windows()
        import win32gui

        found: list[tuple[int, str]] = []

        def collect(hwnd: int, _extra: object) -> None:
            if not include_hidden and not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if title:
                found.append((hwnd, title))

        win32gui.EnumWindows(collect, None)
        return found

    @classmethod
    def matching(cls, titles: list[str], processes: list[str] | None = None) -> "Window":
        _require_windows()
        import win32gui

        hwnd, title, visible = cls._pick(titles, processes or [])

        _, _, width, height = win32gui.GetClientRect(hwnd)
        if win32gui.IsIconic(hwnd) or width <= 0 or height <= 0:
            raise WindowMinimised(
                f"{title!r} is minimised to the taskbar (drawable area "
                f"{width}x{height}). Restore it to resume monitoring."
            )

        left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        frame_left, frame_top, _, _ = win32gui.GetWindowRect(hwnd)
        return cls(
            hwnd=hwnd,
            title=title,
            left=left,
            top=top,
            width=width,
            height=height,
            frame_left=frame_left,
            frame_top=frame_top,
            visible=visible,
            process=process_name(hwnd),
        )

    @classmethod
    def _pick(cls, titles: list[str], processes: list[str]) -> tuple[int, str, bool]:
        """The game window, preferring the process over the title.

        Titles are treacherous: a Discord server called "Black Desert - Sailing"
        and a browser tab about the game both match, and EnumWindows returns
        z-order, so whichever is in front wins. Alt-tabbing to read an alert was
        enough to start screenshotting Discord instead of the game.
        """
        for visible in (True, False):
            found = cls._search(cls.all(include_hidden=not visible), titles, processes)
            if found:
                return found[0], found[1], visible

        raise CaptureError(
            f"No window matching processes {processes} or titles {titles}. "
            "Is the game running, and is window.process_matches correct?"
        )

    @classmethod
    def _search(
        cls, windows: list[tuple[int, str]], titles: list[str], processes: list[str]
    ) -> tuple[int, str] | None:
        wanted = [p.lower() for p in processes]
        by_process = [w for w in windows if process_name(w[0]).lower() in wanted]
        if by_process:
            return by_process[0]

        needles = [t.lower() for t in titles]
        by_title = [w for w in windows if any(n in w[1].lower() for n in needles)]
        if not by_title:
            return None

        if len(by_title) > 1:
            log.warning(
                "No window from %s; falling back to the title, which %d windows "
                "match. Taking %r. Others: %s",
                processes,
                len(by_title),
                by_title[0][1],
                ", ".join(repr(t) for _h, t in by_title[1:]),
            )
        return by_title[0]


def _require_windows() -> None:
    if sys.platform != "win32":
        raise CaptureError("Window lookup is implemented for Windows only.")


class Capture(ABC):
    """Somewhere frames come from."""

    @abstractmethod
    def frame(self, window: Window) -> Image.Image: ...

    def close(self) -> None:
        pass

    def __enter__(self) -> "Capture":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class ScreenCapture(Capture):
    """The desktop rectangle the window sits on, overlapping windows included."""

    def __init__(self) -> None:
        self._sct = mss.mss()

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass

    def frame(self, window: Window) -> Image.Image:
        return self.region(window.left, window.top, window.width, window.height)

    def region(self, left: int, top: int, width: int, height: int) -> Image.Image:
        if width <= 0 or height <= 0:
            raise CaptureError(f"Refusing to capture a {width}x{height} region.")
        raw = self._sct.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.fromarray(np.asarray(raw)[:, :, :3][:, :, ::-1], mode="RGB")


class WindowCapture(Capture):
    """The window's own content, whatever is stacked on top of it.

    Windows Graphics Capture, the API behind OBS's Window Capture. A fresh
    one-shot session per frame costs about 0.15s, which is nothing against a
    30s poll, and avoids holding a capture thread and a stale buffer between
    polls.
    """

    def __init__(self) -> None:
        try:
            from windows_capture import WindowsCapture
        except ImportError as exc:
            raise CaptureError(
                "windows-capture is not installed, so window capture is "
                'unavailable. Run setup.ps1 again, or set capture.method = "screen".'
            ) from exc
        self._session = WindowsCapture

    def frame(self, window: Window) -> Image.Image:
        try:
            captured = self._one_frame(window.hwnd)
        except CaptureError:
            if window.visible:
                raise
            raise WindowMinimised(
                f"{window.title!r} is minimised and delivered no frame. "
                "Restore the window to resume monitoring."
            ) from None
        return self._drawable_area(captured, window)

    @staticmethod
    def _drawable_area(captured: Image.Image, window: Window) -> Image.Image:
        left, top = window.offset
        if (left, top) == (0, 0) and captured.size == window.size:
            return captured
        right = min(captured.width, left + window.width)
        bottom = min(captured.height, top + window.height)
        if right <= left or bottom <= top:
            raise CaptureError(
                f"Drawable area {window.size} at offset {window.offset} does not "
                f"fit the {captured.size} window frame."
            )
        return captured.crop((left, top, right, bottom))

    def _one_frame(self, hwnd: int) -> Image.Image:
        arrived = threading.Event()
        buffer: dict[str, np.ndarray] = {}

        session = self._session(cursor_capture=False, draw_border=False, window_hwnd=hwnd)

        @session.event
        def on_frame_arrived(frame, control):  # type: ignore[no-untyped-def]
            if not arrived.is_set():
                buffer["pixels"] = np.array(frame.frame_buffer, copy=True)
                arrived.set()
                control.stop()

        @session.event
        def on_closed():  # type: ignore[no-untyped-def]
            arrived.set()

        control = session.start_free_threaded()
        got = arrived.wait(CAPTURE_TIMEOUT_SECONDS)
        try:
            control.stop()
        except Exception:
            pass

        pixels = buffer.get("pixels")
        if not got or pixels is None:
            raise CaptureError("Windows Graphics Capture returned no frame.")
        return Image.fromarray(pixels[:, :, :3][:, :, ::-1].astype(np.uint8), mode="RGB")


class PreferredCapture(Capture):
    """Window capture, falling back to the screen once it proves unusable."""

    def __init__(self, preferred: Capture, fallback: Capture) -> None:
        self._preferred: Capture | None = preferred
        self._fallback = fallback

    def frame(self, window: Window) -> Image.Image:
        if self._preferred is not None:
            try:
                captured = self._preferred.frame(window)
            except WindowMinimised:
                raise
            except CaptureError as exc:
                log.warning("Window capture failed (%s); falling back to the screen.", exc)
                self._demote()
            else:
                if not blank(captured):
                    return captured
                log.warning("Window capture came back blank; falling back to the screen.")
                self._demote()

        if not window.visible:
            raise WindowMinimised(
                f"{window.title!r} is hidden, and the desktop behind it shows "
                "other applications rather than the game. Restore the window."
            )
        return self._fallback.frame(window)

    def _demote(self) -> None:
        if self._preferred is not None:
            self._preferred.close()
            self._preferred = None

    def close(self) -> None:
        if self._preferred is not None:
            self._preferred.close()
        self._fallback.close()


def capture_for(method: str) -> Capture:
    if method == "screen":
        return ScreenCapture()
    if method != "window":
        raise CaptureError(f"Unknown capture.method {method!r}; use 'window' or 'screen'.")
    try:
        return PreferredCapture(WindowCapture(), ScreenCapture())
    except CaptureError as exc:
        log.warning("%s Falling back to screen capture.", exc)
        return ScreenCapture()
