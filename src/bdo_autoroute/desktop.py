"""Windows toast notifications.

Knows about the notification centre and nothing about routes. Useful on its own
when you are at the machine, and as a second channel when Discord is down.
"""

from __future__ import annotations

import atexit
import logging
import tempfile
import threading
from pathlib import Path

from .alerts import Alert

log = logging.getLogger(__name__)

TOAST_IMAGE_WIDTH = 480
APP_NAME = "BDO Autoroute Track"

# One fixed path, and one handler for the process. Registering per instance
# leaked a Desktop and its toaster on every hot reload, because build_outbox
# makes a fresh one each time the settings are saved.
SCRATCH_IMAGE = Path(tempfile.gettempdir()) / "bdo-autoroute-toast.png"


def _discard_scratch() -> None:
    """Drop the scratch image. Safe when it was never written."""
    try:
        SCRATCH_IMAGE.unlink(missing_ok=True)
    except OSError as exc:
        log.debug("Could not remove %s: %s", SCRATCH_IMAGE, exc)


atexit.register(_discard_scratch)


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

        self._app_name = app_name
        self._new_toaster = WindowsToaster
        # One toaster per thread, made on first use. WinRT objects belong to
        # the thread that made them. The window builds the outbox on Tk's
        # thread and the poll loop delivers from a worker, and a toaster made
        # on one and shown from the other failed with "marshalled for a
        # different thread" and delivered nothing. The tray alone never showed
        # it, because there the two happened to be the same thread.
        self._local = threading.local()
        self._icon = icon if icon and icon.exists() else None
        self._scratch = SCRATCH_IMAGE

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
            self._toaster().show_toast(toast)
            return True
        except Exception as exc:
            log.warning("Desktop notification failed: %s", exc)
            return False

    def _toaster(self):
        """This thread's toaster, made the first time this thread asks."""
        toaster = getattr(self._local, "toaster", None)
        if toaster is None:
            toaster = self._local.toaster = self._new_toaster(self._app_name)
        return toaster

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
            # Deliberately not deleting here. Windows reads the file while a
            # toast is on screen, and the previous toast may still be up.
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


