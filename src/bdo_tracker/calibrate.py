"""Interactive two-box calibration for the route marker.

The marker follows a world position, so nothing can be pinned to fixed screen
coordinates. Calibration therefore records two things:

  1. a picture of the route icon, used as a template to find the marker again
  2. where the digits sit relative to that icon

You drag a box around the digits, then a box around the icon.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

from .capture import ClientArea, looks_black, make_grabber

DIGITS_PROMPT = (
    "STEP 1 of 2 - drag a box around the DISTANCE DIGITS only.\n"
    "Just the number (for example 600 or 3970). Leave the icon out.\n"
    "Enter or double-click to accept  |  R to redraw  |  Esc to cancel"
)

ICON_PROMPT = (
    "STEP 2 of 2 - now drag a box around the ICON beside the number.\n"
    "Box it tightly: this picture is used to find the marker as it moves.\n"
    "Enter or double-click to accept  |  R to redraw  |  Esc to cancel"
)


class RegionPicker:
    """A one-shot modal picker returning the selected box in image pixels."""

    def __init__(self, frame: Image.Image, prompt: str) -> None:
        self._frame = frame
        self._selection: tuple[int, int, int, int] | None = None
        self._start: tuple[int, int] | None = None
        self._rect_id: int | None = None

        self._root = tk.Tk()
        self._root.title("BDO monitor - calibration")

        # Fit the frame inside the available desktop, leaving room for chrome.
        max_w = self._root.winfo_screenwidth() - 80
        max_h = self._root.winfo_screenheight() - 220
        self._scale = min(1.0, max_w / frame.width, max_h / frame.height)
        view_w = max(1, int(frame.width * self._scale))
        view_h = max(1, int(frame.height * self._scale))

        tk.Label(
            self._root, text=prompt, justify="left", padx=10, pady=8, anchor="w"
        ).pack(fill="x")

        self._canvas = tk.Canvas(self._root, width=view_w, height=view_h, cursor="crosshair")
        self._canvas.pack()
        self._photo = ImageTk.PhotoImage(frame.resize((view_w, view_h), Image.LANCZOS))
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)

        self._status = tk.Label(self._root, text="No selection yet.", padx=10, pady=6, anchor="w")
        self._status.pack(fill="x")

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Double-Button-1>", lambda _e: self._accept())
        self._root.bind("<Return>", lambda _e: self._accept())
        self._root.bind("<Escape>", lambda _e: self._cancel())
        self._root.bind("r", lambda _e: self._clear())
        self._root.bind("R", lambda _e: self._clear())

    # -- mouse handling --------------------------------------------------

    def _on_press(self, event: "tk.Event[tk.Canvas]") -> None:
        self._clear()
        self._start = (event.x, event.y)

    def _on_drag(self, event: "tk.Event[tk.Canvas]") -> None:
        if self._start is None:
            return
        x0, y0 = self._start
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
        self._rect_id = self._canvas.create_rectangle(
            x0, y0, event.x, event.y, outline="#00ff88", width=2
        )

    def _on_release(self, event: "tk.Event[tk.Canvas]") -> None:
        if self._start is None:
            return
        x0, y0 = self._start
        left, right = sorted((x0, event.x))
        top, bottom = sorted((y0, event.y))

        # Map the on-screen selection back to full-resolution frame pixels.
        to_px = lambda v: int(round(v / self._scale))  # noqa: E731
        sel = (to_px(left), to_px(top), to_px(right - left), to_px(bottom - top))
        if sel[2] < 4 or sel[3] < 4:
            self._status.config(text="That box is too small. Drag a larger one.")
            self._selection = None
            return
        self._selection = sel
        self._status.config(
            text=f"Selected {sel[2]}x{sel[3]}px at ({sel[0]}, {sel[1]}). "
            "Press Enter to accept, or drag again."
        )

    # -- lifecycle -------------------------------------------------------

    def _clear(self) -> None:
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
            self._rect_id = None
        self._selection = None
        self._start = None
        self._status.config(text="No selection yet.")

    def _accept(self) -> None:
        if self._selection is None:
            self._status.config(text="Drag a box first.")
            return
        self._root.destroy()

    def _cancel(self) -> None:
        self._selection = None
        self._root.destroy()

    def run(self) -> tuple[int, int, int, int] | None:
        self._root.mainloop()
        return self._selection


def capture_frame(area: ClientArea, method: str = "window") -> Image.Image:
    with make_grabber(method) as grabber:
        return grabber.grab_client(area)


def warn_if_black(frame: Image.Image) -> bool:
    if not looks_black(frame):
        return False
    print(
        "Warning: the captured frame is entirely black. Black Desert is probably\n"
        "running in Fullscreen Exclusive mode. Switch it to Borderless Windowed\n"
        "under Settings > Display, then run calibrate again."
    )
    return True


def pick_boxes(
    frame: Image.Image,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None:
    """Ask for the digits box, then the icon box. None if cancelled."""
    digits = RegionPicker(frame, DIGITS_PROMPT).run()
    if digits is None:
        return None
    icon = RegionPicker(frame, ICON_PROMPT).run()
    if icon is None:
        return None
    return digits, icon


def save_preview(images: dict[str, Image.Image], out_dir: Path) -> list[Path]:
    """Write named debug images so a failed calibration can be diagnosed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, image in images.items():
        path = out_dir / f"{name}.png"
        image.save(path)
        written.append(path)
    return written
