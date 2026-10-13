"""High-level operations for keyboards that speak the HFD protocol (the INFI75).

Shared by the CLI and the GUI. Each operation opens the configuration
interface (libusb, interface 3) for its duration, or only logs packets in
dry-run mode.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import hfd, screen, usbctl
from .profile import Profile
from .transport import DeviceError, _hid, enumerate_interfaces


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "infi75"


def keymap_state_path() -> Path:
    return config_dir() / "keymap.json"


def colors_state_path() -> Path:
    return config_dir() / "colors.json"


class InfiBoard:
    def __init__(self, profile: Profile, vendor_id: int | None = None, product_id: int | None = None,
                 dry_run: bool = False, log: Callable[[str], None] | None = None) -> None:
        if profile.protocol != "hfd":
            raise DeviceError(f"profile '{profile.name}' does not use the HFD protocol")
        self.profile = profile
        self.vendor_id = vendor_id if vendor_id is not None else profile.vendor_id
        self.product_id = product_id if product_id is not None else (
            profile.product_ids[0] if profile.product_ids else None)
        self.dry_run = dry_run
        self.log = log or (lambda msg: print(msg, file=sys.stderr))

    # ------------------------------------------------------------ plumbing

    def _session(self):
        if self.dry_run:
            return hfd.Session(None, dry_run=True, log=self.log), nullcontext()
        if self.product_id is None:
            raise DeviceError("profile has no product id; pass --pid")
        link = usbctl.UsbHid(self.vendor_id, self.product_id,
                             self.profile.lighting_interface or hfd.CONFIG_INTERFACE)
        return hfd.Session(link, log=self.log), link

    def _run(self, action) -> None:
        session, link = self._session()
        with link:
            action(session)

    # ------------------------------------------------------------ lighting

    @staticmethod
    def effects() -> list[str]:
        return ["off", *hfd.EFFECTS]

    def set_lighting(self, effect: str, color=(255, 255, 255), brightness: int = 5, speed: int = 3,
                     rainbow: bool = False, direction: str = "right") -> None:
        if effect.strip().lower() == "off":
            mode, brightness = hfd.OFF
        else:
            mode = hfd.resolve_mode(effect)
        settings = hfd.Lighting(mode=mode, color=tuple(color), rainbow=rainbow, brightness=brightness,
                                speed=speed, direction=hfd.DIRECTIONS[direction])
        self._run(lambda s: s.set_lighting(settings))

    def set_key_colors(self, colors: dict[str, tuple[int, int, int]], default=(0, 0, 0),
                       brightness: int = 5) -> None:
        chosen = {self.profile.key(name).name: tuple(rgb) for name, rgb in colors.items()}
        table = {key.index: chosen.get(key.name, tuple(default)) for key in self.profile.keys}
        self._run(lambda s: s.set_key_colors(table, brightness=brightness))
        if not self.dry_run:
            path = colors_state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"default": list(default),
                                        "keys": {k: list(v) for k, v in sorted(chosen.items())}}, indent=2))

    def saved_colors(self) -> tuple[dict[str, tuple[int, int, int]], tuple[int, int, int]]:
        """The per-key colours last written by this tool: ({key: rgb}, default)."""
        try:
            data = json.loads(colors_state_path().read_text())
            keys = {k: tuple(v) for k, v in data.get("keys", {}).items()}
            return keys, tuple(data.get("default", (0, 0, 0)))
        except (OSError, ValueError):
            return {}, (0, 0, 0)

    def connection(self) -> str:
        """'usb' (configurable), 'bluetooth' (connected, not configurable) or 'none'."""
        try:
            import usb.core

            if self.product_id is not None and usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id):
                return "usb"
        except Exception:  # libusb missing or not accessible
            pass
        from . import probe

        try:
            nodes = probe.linux_nodes(self.vendor_id, self.product_id or 0)
        except OSError:
            nodes = []
        return "bluetooth" if any(n.interface == -1 for n in nodes) else "none"

    # -------------------------------------------------------------- keymap

    def remaps(self) -> dict[str, str]:
        path = keymap_state_path()
        try:
            return json.loads(path.read_text()) if path.exists() else {}
        except (OSError, ValueError):
            return {}

    def write_remaps(self, state: dict[str, str]) -> None:
        """Write the full base-layer table; keys not in *state* keep their default."""
        entries = {self.profile.key(name).index: hfd.key_entry(target) for name, target in state.items()}
        self._run(lambda s: s.write_keymap(entries))
        if not self.dry_run:
            path = keymap_state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, indent=2, sort_keys=True))

    def remap(self, key_name: str, target: str) -> dict[str, str]:
        key = self.profile.key(key_name)
        hfd.key_entry(target)  # validate before storing
        state = self.remaps()
        if target.strip().lower() in ("default", "reset"):
            state.pop(key.name, None)
        else:
            state[key.name] = target
        self.write_remaps(state)
        return state

    def reset_remaps(self) -> None:
        self.write_remaps({})

    # -------------------------------------------------------------- screen

    def sync_time(self, when: datetime | None = None) -> None:
        self._run(lambda s: s.sync_time(when))

    def upload_image(self, path: str | Path, fit: str = "crop", slot: int = 1,
                     progress: Callable[[int, int], None] | None = None) -> int:
        frames = screen.frames_from_file(path, hfd.SCREEN_WIDTH, hfd.SCREEN_HEIGHT,
                                         hfd.SCREEN_MAX_FRAMES, fit=fit)
        if self.dry_run:
            self._run(lambda s: s.upload_screen(frames, None, slot=slot))
            return len(frames)
        pipe = self._screen_pipe()
        try:
            self._run(lambda s: s.upload_screen(frames, pipe, slot=slot, progress=progress))
        finally:
            pipe.close()
        return len(frames)

    def _screen_pipe(self):
        """hidraw handle on the screen interface (0xFF68), which the kernel HID driver serves."""
        for interface in enumerate_interfaces(self.vendor_id, self.product_id or 0):
            if interface.interface == hfd.SCREEN_INTERFACE:
                device = _hid().device()
                device.open_path(interface.path)
                return device
        raise DeviceError(f"screen interface {hfd.SCREEN_INTERFACE} not found")
