"""Macro sequences in a short text form, and conversion to the keyboard's events.

Tokens, separated by spaces or commas:

* ``a``, ``enter``, ``ctrl+c``  press and release (a combination holds the modifiers around the key)
* ``+shift`` / ``-shift``       hold / release a key
* ``50ms``                       wait (0-65535 ms)
* ``text:hello``                 type letters, digits and spaces (capitals use shift)
* ``mouse1``, ``+mouse2``, ...   mouse buttons 1-3 (left, right, middle)

The keyboard inserts nothing by itself; the vendor driver adds a 10 ms gap
between two events that have no delay between them, and so does this tool.
"""

from __future__ import annotations

import re

from . import hidkeys

Event = tuple[str, int]  # ("down" | "up" | "delay" | "mouse_down" | "mouse_up", value)

_DELAY = re.compile(r"^(\d+)\s*ms$")
_MOUSE = re.compile(r"^mouse([123])$")


class MacroError(ValueError):
    pass


def _usage(name: str) -> int:
    try:
        return hidkeys.code(name)
    except KeyError as exc:
        raise MacroError(f"unknown key {name!r} in macro") from exc


def _tap(name: str) -> list[Event]:
    mouse = _MOUSE.match(name)
    if mouse:
        button = int(mouse[1])
        return [("mouse_down", button), ("mouse_up", button)]
    parts = [p for p in name.split("+") if p]
    if not parts:
        raise MacroError("empty key in macro")
    codes = [_usage(p) for p in parts]
    return [("down", c) for c in codes] + [("up", c) for c in reversed(codes)]


def _type_text(text: str) -> list[Event]:
    events: list[Event] = []
    shift = _usage("lshift")
    for char in text:
        if char == " ":
            events += _tap("space")
        elif char.isalnum() and char.isascii():
            key = _usage(char.lower())
            if char.isupper():
                events += [("down", shift), ("down", key), ("up", key), ("up", shift)]
            else:
                events += [("down", key), ("up", key)]
        else:
            raise MacroError(f"text: supports letters, digits and spaces; use key names for {char!r}")
    return events


def parse(text: str) -> list[Event]:
    events: list[Event] = []
    for raw in re.findall(r"text:\S*|[^\s,]+", text.strip()):
        token = raw if raw.startswith("text:") else raw.lower()
        if token.startswith("text:"):
            events += _type_text(token[5:].replace("_", " "))
            continue
        delay = _DELAY.match(token)
        if delay:
            ms = int(delay[1])
            if ms > 0xFFFF:
                raise MacroError(f"delay {ms} ms is longer than 65535 ms")
            events.append(("delay", ms))
        elif token[0] in "+-" and len(token) > 1:
            name = token[1:]
            mouse = _MOUSE.match(name)
            if mouse:
                events.append(("mouse_down" if token[0] == "+" else "mouse_up", int(mouse[1])))
            else:
                events.append(("down" if token[0] == "+" else "up", _usage(name)))
        else:
            events += _tap(token)
    if not events:
        raise MacroError("the macro is empty")
    return events


def describe(events: list[Event]) -> str:
    """Short human-readable summary, e.g. 'ctrl+c, 50 ms, enter'."""
    out: list[str] = []
    held: list[int] = []
    fresh = False  # a key went down since the last combination was written
    for kind, value in events:
        if kind == "delay":
            out.append(f"{value} ms")
        elif kind == "down":
            held.append(value)
            fresh = True
        elif kind == "up":
            if fresh and value in held:
                out.append("+".join(hidkeys.name(c) for c in held))
                fresh = False
            if value in held:
                held.remove(value)
        elif kind == "mouse_down":
            out.append(f"mouse{value}")
    return ", ".join(out)
