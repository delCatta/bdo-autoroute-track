"""Dragging boxes over a captured frame.

Two boxes are asked for: the digits, then the icon beside them. The icon becomes
the template used to find the marker again as it moves, and the digits box is
stored relative to it.
"""

from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageTk

from .marker import Box

DIGITS_PROMPT = (
    "STEP 1 of 2. Drag a box around the DISTANCE DIGITS only.\n"
    "Just the number, for example 600 or 3970. Leave the icon out.\n"
    "Enter or double-click to accept  |  R to redraw  |  Esc to cancel"
)

ICON_PROMPT = (
    "STEP 2 of 2. Now drag a box around the ICON beside the number.\n"
    "Box it tightly: this picture is used to find the marker as it moves.\n"
    "Enter or double-click to accept  |  R to redraw  |  Esc to cancel"
)

MINIMUM_BOX_PX = 4


class Picker:
    """One modal drag over a frame, returning the box in full-resolution pixels."""

    def __init__(self, frame: Image.Image, prompt: str) -> None:
        self._selection: Box | None = None
        self._start: tuple[int, int] | None = None
        self._rectangle: int | None = None

        self._root = tk.Tk()
        self._root.title("BDO Autoroute Track calibration")

        available_width = self._root.winfo_screenwidth() - 80
        available_height = self._root.winfo_screenheight() - 220
        self._scale = min(1.0, available_width / frame.width, available_height / frame.height)
        width = max(1, int(frame.width * self._scale))
        height = max(1, int(frame.height * self._scale))

        tk.Label(self._root, text=prompt, justify="left", padx=10, pady=8, anchor="w").pack(
            fill="x"
        )
        self._canvas = tk.Canvas(self._root, width=width, height=height, cursor="crosshair")
        self._canvas.pack()
        self._photo = ImageTk.PhotoImage(frame.resize((width, height), Image.LANCZOS))
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)

        self._status = tk.Label(self._root, text="No selection yet.", padx=10, pady=6, anchor="w")
        self._status.pack(fill="x")

        self._bind()

    def box(self) -> Box | None:
        self._root.mainloop()
        return self._selection

    def _bind(self) -> None:
        self._canvas.bind("<ButtonPress-1>", self._press)
        self._canvas.bind("<B1-Motion>", self._drag)
        self._canvas.bind("<ButtonRelease-1>", self._release)
        self._canvas.bind("<Double-Button-1>", lambda _e: self._accept())
        self._root.bind("<Return>", lambda _e: self._accept())
        self._root.bind("<Escape>", lambda _e: self._cancel())
        for key in ("r", "R"):
            self._root.bind(key, lambda _e: self._clear())

    def _press(self, event) -> None:
        self._clear()
        self._start = (event.x, event.y)

    def _drag(self, event) -> None:
        if self._start is None:
            return
        if self._rectangle is not None:
            self._canvas.delete(self._rectangle)
        self._rectangle = self._canvas.create_rectangle(
            *self._start, event.x, event.y, outline="#00ff88", width=2
        )

    def _release(self, event) -> None:
        if self._start is None:
            return
        left, right = sorted((self._start[0], event.x))
        top, bottom = sorted((self._start[1], event.y))
        box = Box(*(self._full_size(v) for v in (left, top, right - left, bottom - top)))

        if box.width < MINIMUM_BOX_PX or box.height < MINIMUM_BOX_PX:
            self._selection = None
            self._status.config(text="That box is too small. Drag a larger one.")
            return

        self._selection = box
        self._status.config(
            text=f"Selected {box.width}x{box.height}px at {box.origin}. "
            "Press Enter to accept, or drag again."
        )

    def _full_size(self, value: int) -> int:
        return int(round(value / self._scale))

    def _clear(self) -> None:
        if self._rectangle is not None:
            self._canvas.delete(self._rectangle)
            self._rectangle = None
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


def digits_and_icon(frame: Image.Image) -> tuple[Box, Box] | None:
    """Ask for both boxes. None when cancelled."""
    digits = Picker(frame, DIGITS_PROMPT).box()
    if digits is None:
        return None
    icon = Picker(frame, ICON_PROMPT).box()
    if icon is None:
        return None
    return digits, icon
