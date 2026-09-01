"""Windows toast notifications.

Knows about the notification centre and nothing about routes. Useful on its own
when you are at the machine, and as a second channel when Discord is down.
"""

from __future__ import annotations

import atexit
import logging
import tempfile
from pathlib import Path

from .alerts import Alert

log = logging.getLogger(__name__)

TOAST_IMAGE_WIDTH = 480
APP_NAME = "BDO Autoroute Track"


class Desktop:
    """Toasts into the Windows notification centre."""

    name = "desktop"

    def __init__(self, *, app_name: str = APP_NAME, icon: Path | None = None) -> None:
        try:
            from windows_toasts import WindowsToaster
        except ImportError as exc:
            raise RuntimeError(
                "windows-toasts is not installed, so desktop notifications are "
                'unavailable. Run setup.cmd again, or drop "desktop" from '
                "notify.channels."
            ) from exc

        self._toaster = WindowsToaster(app_name)
        self._icon = icon if icon and icon.exists() else None
        self._scratch = Path(tempfile.gettempdir()) / "bdo-autoroute-toast.png"
        # Windows reads the file while the toast is on screen, so it cannot go
        # straight after showing one. Clearing it at exit keeps the last game
        # frame from sitting in %TEMP% after the monitor has stopped.
        atexit.register(self._discard)

    def deliver(self, alert: Alert) -> bool:
        """Raise one toast. True on success; never raises."""
        try:
            from windows_toasts import Toast

            toast = Toast()
            # Three lines, not two. The ETA and the stall clock live in the
            # details, and a toast without them said "Still under way" and
            # nothing a person could act on.
            toast.text_fields = [alert.headline, alert.body, alert.footnote]
            self._attach_images(toast, alert)
            self._toaster.show_toast(toast)
            return True
        except Exception as exc:
            log.warning("Desktop notification failed: %s", exc)
            return False

    def _attach_images(self, toast, alert: Alert) -> None:
        """Best effort: a toast without pictures still tells you what happened."""
        try:
            from windows_toasts import ToastDisplayImage, ToastImagePosition
        except ImportError:
            return

        if self._icon is not None:
            try:
                toast.AddImage(
                    ToastDisplayImage.fromPath(
                        self._icon, position=ToastImagePosition.AppLogo
                    )
                )
            except Exception as exc:
                log.debug("Could not attach the app logo: %s", exc)

        shot = alert.thumbnail(TOAST_IMAGE_WIDTH)
        if shot is None:
            self._discard()
            return
        try:
            shot.convert("RGB").save(self._scratch, format="PNG")
            # Inline, not Hero: plain toasts silently drop hero images, and
            # only warn about it on stderr.
            toast.AddImage(
                ToastDisplayImage.fromPath(self._scratch, position=ToastImagePosition.Inline)
            )
        except Exception as exc:
            log.debug("Could not attach the screenshot: %s", exc)

    def _discard(self) -> None:
        """Drop the scratch image. Safe when it was never written."""
        try:
            self._scratch.unlink(missing_ok=True)
        except OSError as exc:
            log.debug("Could not remove %s: %s", self._scratch, exc)
