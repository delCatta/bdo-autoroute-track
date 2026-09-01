"""Editing config.toml in place, without losing what it says.

Every setting in that file is explained by a comment above it, and those
comments are most of its value. A round trip through a TOML library would
rewrite the file and throw them away, so values are replaced line by line and
everything else is left exactly as it was.
"""

from __future__ import annotations

import re
from pathlib import Path

SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")


# The characters TOML gives a short escape to in a basic string.
ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def escaped(text: str) -> str:
    """One TOML basic string body, with everything it forbids spelled out.

    A pasted value can carry a newline, and TOML forbids every control character
    here, not only that one. Writing one raw produced a config.toml that no
    longer parsed, and the failure was quiet: a running monitor keeps its stale
    settings while the dialog falls back to defaults, so the next save could
    reset unrelated values.
    """
    out = []
    for ch in text:
        if ch in ESCAPES:
            out.append(ESCAPES[ch])
        elif ch < " " or ch == "\x7f":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)


def as_toml(value: object) -> str:
    """Render a Python value the way TOML spells it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(as_toml(item) for item in value) + "]"
    return f'"{escaped(str(value))}"'


class ConfigFile:
    """One config.toml, editable a value at a time."""

    def __init__(self, path: Path) -> None:
        self.path = path
        # newline="" or universal-newline translation hides the CRLF we are
        # trying to detect, and the file would quietly be rewritten as LF.
        raw = ""
        if path.exists():
            with path.open("r", encoding="utf-8", newline="") as handle:
                raw = handle.read()
        self._crlf = "\r\n" in raw
        self._lines = raw.replace("\r\n", "\n").split("\n")

    def get(self, section: str, key: str) -> str | None:
        """The raw text of a value, or None if the key is not there."""
        index = self._index_of(section, key)
        return None if index is None else self._lines[index].split("=", 1)[1].strip()

    def set(self, section: str, key: str, value: object) -> None:
        """Replace a value, keeping its comment and position."""
        rendered = f"{key} = {as_toml(value)}"
        index = self._index_of(section, key)
        if index is not None:
            self._lines[index] = rendered
            return
        self._append_to(section, rendered)

    def save(self) -> Path:
        text = "\n".join(self._lines)
        self.path.write_text(
            text.replace("\n", "\r\n") if self._crlf else text,
            encoding="utf-8",
            newline="",
        )
        return self.path

    # -- finding things --------------------------------------------------

    def _index_of(self, section: str, key: str) -> int | None:
        assignment = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for index in self._section_body(section):
            if assignment.match(self._lines[index]):
                return index
        return None

    def _section_body(self, section: str) -> list[int]:
        """Line numbers belonging to a section, excluding its header."""
        body: list[int] = []
        inside = False
        for index, line in enumerate(self._lines):
            heading = SECTION.match(line)
            if heading:
                inside = heading.group(1) == section
                continue
            if inside:
                body.append(index)
        return body

    def _append_to(self, section: str, rendered: str) -> None:
        body = self._section_body(section)
        if not body:
            if self._lines and self._lines[-1].strip():
                self._lines.append("")
            self._lines.extend([f"[{section}]", rendered])
            return

        last = body[-1]
        while last > body[0] and not self._lines[last].strip():
            last -= 1
        self._lines.insert(last + 1, rendered)
