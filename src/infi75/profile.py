"""Keyboard profiles: USB identity, protocol tuning, key indices and screen geometry.

The bundled profile is a starting point. Copy it, adjust it to match your
board, and pass it with ``--profile path/to/profile.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True)
class Key:
    name: str
    index: int
    row: int
    x: float
    w: float = 1.0
    code: str = ""  # default HID usage, as in the vendor layout
    fn: bool = True  # False: the firmware reserves Fn + this key (fnlayer_disable in the vendor layout)


@dataclass
class Profile:
    name: str
    vendor_id: int
    product_ids: list[int]
    lighting_interface: int | None
    screen_interface: int | None
    report_type: str
    packet_size: int
    pacing_ms: int
    erase_delay_ms: int
    rgb_slots: int
    screen_width: int | None
    screen_height: int | None
    screen_transpose: bool
    keys: list[Key] = field(default_factory=list)
    verified: bool = False
    protocol: str = "unconfirmed"
    source: str = ""

    def key(self, name: str) -> Key:
        """Look up a physical key by profile name (case-insensitive) or ``#index``."""
        wanted = name.strip()
        if wanted.startswith("#"):
            index = int(wanted[1:], 0)
            for key in self.keys:
                if key.index == index:
                    return key
            return Key(name=wanted, index=index, row=-1, x=-1)
        for key in self.keys:
            if key.name.lower() == wanted.lower():
                return key
        raise KeyError(f"no key named {name!r} in profile {self.name!r}; run 'infi75 keys'")


def _int(value) -> int:
    return int(value, 0) if isinstance(value, str) else int(value)


def load(path: str | Path | None = None) -> Profile:
    """Load a profile from *path*, or the bundled INFI75 profile when *path* is None."""
    if path is None:
        resource = files("infi75.profiles").joinpath("infi75.json")
        text, source = resource.read_text(encoding="utf-8"), "builtin:infi75.json"
    else:
        text, source = Path(path).read_text(encoding="utf-8"), str(path)
    data = json.loads(text)
    usb = data["usb"]
    screen = data.get("screen", {})
    return Profile(
        name=data["name"],
        vendor_id=_int(usb["vendor_id"]),
        product_ids=[_int(p) for p in usb.get("product_ids", [])],
        lighting_interface=usb.get("lighting_interface"),
        screen_interface=usb.get("screen_interface"),
        report_type=usb.get("report_type", "feature"),
        packet_size=int(data.get("packet_size", 64)),
        pacing_ms=int(data.get("pacing_ms", 10)),
        erase_delay_ms=int(data.get("erase_delay_ms", 250)),
        rgb_slots=int(data.get("rgb_slots", 130)),
        screen_width=screen.get("width"),
        screen_height=screen.get("height"),
        screen_transpose=bool(screen.get("transpose", True)),
        keys=[Key(**k) for k in data.get("keys", [])],
        verified=bool(data.get("verified", False)),
        protocol=data.get("protocol", "unconfirmed"),
        source=source,
    )
