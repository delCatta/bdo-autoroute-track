"""Find the Black Desert client window and grab pixels from it.

Read-only: this module never sends input to the game, never reads its memory,
and never injects anything into the process. It only looks at pixels.

Two capture backends:

  window  Windows Graphics Capture, targeted at the game's window handle. Gets
          the game's own content, so overlapping windows never appear in the
          frame and you can use the PC while the monitor runs. This is what OBS
          calls "Window Capture". Default.
  screen  Grab the desktop rectangle where the window happens to sit. Simple and
          dependency-light, but anything covering the game lands in the frame
          and corrupts the reading.

PrintWindow/GDI is deliberately not used: it returns an all-black frame for the
Black Desert client, as it does for most DirectX games.
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

# How long to wait for the compositor to hand over a frame.
_WGC_TIMEOUT_SECONDS = 5.0


class CaptureError(RuntimeError):
    pass


class WindowMinimisedError(CaptureError):
    """The game cannot be captured because it is minimised or hidden.

    Two different real behaviours are covered, both measured on this machine:

      Ordinary window   IsIconic=True, client 0x0, rect (-32000,-32000), and
                        Graphics Capture never delivers a frame. Unreadable.
      Black Desert      IsIconic=FALSE, client stays 3440x1440 at (0,0), but
                        the window drops out of the visible enumeration. So the
                        obvious IsIconic and 0x0 checks never fire for it.

    Because the game keeps a valid rect, capture is attempted anyway rather than
    refused on principle - only a missing frame proves it cannot be read.
    """


@dataclass(frozen=True)
class ClientArea:
    """The game's drawable area, plus what is needed to capture it."""

    left: int
    top: int
    width: int
    height: int
    title: str
    hwnd: int
    # The window's outer rectangle. Window capture returns the whole window, so
    # the client area has to be cropped out of it by this offset.
    window_left: int
    window_top: int
    window_width: int
    window_height: int
    # False when Win32 no longer considers the window visible. Black Desert
    # hides itself rather than truly minimising: it keeps a full-size rect but
    # drops out of the visible list. Capture is attempted anyway - only a
    # missing frame proves it cannot be read - but screen-capture fallback is
    # refused, since the desktop there shows other apps, not the game.
    visible: bool = True

    @property
    def client_offset(self) -> tuple[int, int]:
        """Where the client area starts inside the window frame."""
        return self.left - self.window_left, self.top - self.window_top


def list_windows(*, include_hidden: bool = False) -> list[tuple[int, str]]:
    """Titled top-level windows, as (hwnd, title).

    `include_hidden` also returns windows Win32 does not consider visible.
    Black Desert drops out of the visible list entirely while minimised, so
    that pass is what tells "minimised" apart from "not running".
    """
    if sys.platform != "win32":
        raise CaptureError("Window lookup is implemented for Windows only.")

    import win32gui

    found: list[tuple[int, str]] = []

    def _collect(hwnd: int, _extra: object) -> None:
        if not include_hidden and not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title:
            found.append((hwnd, title))

    win32gui.EnumWindows(_collect, None)
    return found


def find_client_area(title_matches: list[str]) -> ClientArea:
    """Locate the game window and describe its client area.

    The client area excludes the title bar and borders, so a region stored as a
    fraction of it stays correct across window moves and resolution changes.
    """
    if sys.platform != "win32":
        raise CaptureError("Window lookup is implemented for Windows only.")

    import win32gui

    needles = [t.lower() for t in title_matches]
    matches = [(h, t) for h, t in list_windows() if any(n in t.lower() for n in needles)]

    visible = bool(matches)
    if not matches:
        # Minimised windows vanish from the visible list, so a plain "not found"
        # here would send the user off to check whether the game is even running.
        matches = [
            (h, t)
            for h, t in list_windows(include_hidden=True)
            if any(n in t.lower() for n in needles)
        ]
        if not matches:
            raise CaptureError(
                f"No window matching {title_matches}. "
                "Is the game running, and is window.title_matches correct?"
            )

    hwnd, title = matches[0]

    # A genuinely minimised window is parked off-screen at (-32000, -32000)
    # with a 0x0 client area, and nothing can read it. Black Desert does not do
    # this - it keeps its rect and merely goes invisible - so the two cases are
    # separated here rather than assumed to be the same.
    _, _, cw, ch = win32gui.GetClientRect(hwnd)
    if win32gui.IsIconic(hwnd) or cw <= 0 or ch <= 0:
        raise WindowMinimisedError(
            f"{title!r} is minimised to the taskbar (client area {cw}x{ch}), so "
            "there is nothing to capture. Restore it to resume monitoring."
        )
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    wl, wt, wr, wb = win32gui.GetWindowRect(hwnd)

    return ClientArea(
        left=left,
        top=top,
        width=cw,
        height=ch,
        title=title,
        hwnd=hwnd,
        window_left=wl,
        window_top=wt,
        window_width=wr - wl,
        window_height=wb - wt,
        visible=visible,
    )


def looks_black(image: Image.Image, threshold: int = 8) -> bool:
    """True if the frame is essentially all black.

    Fullscreen Exclusive mode defeats screen capture and yields black frames;
    catching that lets us print a useful message instead of silently reporting
    "no distance found" forever.
    """
    return bool(np.asarray(image.convert("L")).max() <= threshold)


class FrameGrabber(ABC):
    """Produces frames of the game's client area."""

    @abstractmethod
    def grab_client(self, area: ClientArea) -> Image.Image: ...

    def close(self) -> None:  # pragma: no cover - most backends need nothing
        pass

    def __enter__(self) -> "FrameGrabber":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class ScreenGrabber(FrameGrabber):
    """Grabs the desktop rectangle the window occupies.

    Simple, but it photographs whatever is on top: overlapping windows end up in
    the frame and will corrupt the reading. Prefer WindowGrabber.
    """

    def __init__(self) -> None:
        self._sct = mss.mss()

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:  # pragma: no cover - best-effort teardown
            pass

    def grab(self, left: int, top: int, width: int, height: int) -> Image.Image:
        if width <= 0 or height <= 0:
            raise CaptureError(f"Refusing to capture a {width}x{height} region.")
        raw = self._sct.grab({"left": left, "top": top, "width": width, "height": height})
        # mss hands back BGRA; drop alpha and flip to RGB.
        arr = np.asarray(raw)[:, :, :3][:, :, ::-1]
        return Image.fromarray(arr, mode="RGB")

    def grab_client(self, area: ClientArea) -> Image.Image:
        return self.grab(area.left, area.top, area.width, area.height)


class WindowGrabber(FrameGrabber):
    """Captures the game window itself via Windows Graphics Capture.

    Targets the window handle, so the frame is the game's own content whatever
    is stacked on top of it. A fresh one-shot session is used per grab: it costs
    roughly 0.15s, which is nothing against a 30s poll, and avoids holding a
    capture thread and a stale frame buffer between polls.
    """

    def __init__(self) -> None:
        try:
            from windows_capture import WindowsCapture
        except ImportError as exc:
            raise CaptureError(
                "windows-capture is not installed, so window capture is "
                "unavailable. Run setup.ps1 again, or set capture.method = "
                '"screen" in config.toml.'
            ) from exc
        self._WindowsCapture = WindowsCapture

    def grab_client(self, area: ClientArea) -> Image.Image:
        try:
            frame = self._grab_window(area.hwnd)
        except CaptureError:
            if not area.visible:
                raise WindowMinimisedError(
                    f"{area.title!r} is minimised and delivered no frame, so "
                    "monitoring is paused. Restore the window to resume."
                ) from None
            raise

        offset_x, offset_y = area.client_offset
        # Borderless windowed has no chrome, so this is usually a no-op. In
        # windowed mode it trims the title bar and borders off.
        if (offset_x, offset_y) != (0, 0) or frame.size != (area.width, area.height):
            right = min(frame.width, offset_x + area.width)
            bottom = min(frame.height, offset_y + area.height)
            if right <= offset_x or bottom <= offset_y:
                raise CaptureError(
                    f"Client area {area.width}x{area.height} at offset "
                    f"{(offset_x, offset_y)} does not fit the {frame.size} window frame."
                )
            frame = frame.crop((offset_x, offset_y, right, bottom))
        return frame

    def _grab_window(self, hwnd: int) -> Image.Image:
        done = threading.Event()
        holder: dict[str, object] = {}

        capture = self._WindowsCapture(
            cursor_capture=False,
            draw_border=False,  # suppress the Windows 11 yellow capture border
            window_hwnd=hwnd,
        )

        @capture.event
        def on_frame_arrived(frame, capture_control):  # type: ignore[no-untyped-def]
            if not done.is_set():
                holder["buffer"] = np.array(frame.frame_buffer, copy=True)
                done.set()
                capture_control.stop()

        @capture.event
        def on_closed():  # type: ignore[no-untyped-def]
            done.set()

        control = capture.start_free_threaded()
        arrived = done.wait(_WGC_TIMEOUT_SECONDS)
        try:
            control.stop()
        except Exception:  # pragma: no cover - the session may already be gone
            pass

        buffer = holder.get("buffer")
        if not arrived or buffer is None:
            raise CaptureError(
                "Windows Graphics Capture returned no frame for the game window. "
                "Is it minimised?"
            )
        arr = np.asarray(buffer)
        # BGRA -> RGB.
        return Image.fromarray(arr[:, :, :3][:, :, ::-1].astype(np.uint8), mode="RGB")


class FallbackGrabber(FrameGrabber):
    """Uses window capture, falling back to screen capture if it cannot work.

    The fallback is sticky: once screen capture takes over it stays, so a
    failing backend is not retried on every poll.
    """

    def __init__(self, preferred: FrameGrabber, fallback: FrameGrabber) -> None:
        self._preferred: FrameGrabber | None = preferred
        self._fallback = fallback

    def grab_client(self, area: ClientArea) -> Image.Image:
        if self._preferred is not None:
            try:
                frame = self._preferred.grab_client(area)
            except WindowMinimisedError:
                raise
            except CaptureError as exc:
                log.warning("Window capture failed (%s); falling back to screen capture.", exc)
                self._demote()
            else:
                if not looks_black(frame):
                    return frame
                log.warning(
                    "Window capture produced an all-black frame; "
                    "falling back to screen capture."
                )
                self._demote()
        if not area.visible:
            # Screen capture would photograph whatever is on the desktop where
            # the hidden window nominally sits - other apps, not the game.
            raise WindowMinimisedError(
                f"{area.title!r} is hidden; screen capture there would show the "
                "desktop, not the game. Restore the window to resume."
            )
        return self._fallback.grab_client(area)

    def _demote(self) -> None:
        if self._preferred is not None:
            self._preferred.close()
            self._preferred = None

    def close(self) -> None:
        if self._preferred is not None:
            self._preferred.close()
        self._fallback.close()


def make_grabber(method: str) -> FrameGrabber:
    """Build the grabber for the configured capture method."""
    if method == "screen":
        return ScreenGrabber()
    if method != "window":
        raise CaptureError(f"Unknown capture.method {method!r}; use 'window' or 'screen'.")
    try:
        return FallbackGrabber(WindowGrabber(), ScreenGrabber())
    except CaptureError as exc:
        log.warning("%s Falling back to screen capture.", exc)
        return ScreenGrabber()
