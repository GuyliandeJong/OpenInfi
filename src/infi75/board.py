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


def lighting_state_path() -> Path:
    return config_dir() / "lighting.json"


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


class InfiBoard:
    def __init__(self, profile: Profile, vendor_id: int | None = None, product_id: int | None = None,
                 dry_run: bool = False, log: Callable[[str], None] | None = None, trace: bool = False) -> None:
        if profile.protocol != "hfd":
            raise DeviceError(f"profile '{profile.name}' does not use the HFD protocol")
        self.profile = profile
        self.vendor_id = vendor_id if vendor_id is not None else profile.vendor_id
        self.product_id = product_id if product_id is not None else (
            profile.product_ids[0] if profile.product_ids else None)
        self.dry_run = dry_run
        self.trace = trace
        self.log = log or (lambda msg: print(msg, file=sys.stderr))

    # ------------------------------------------------------------ plumbing

    def _session(self):
        if self.dry_run:
            return hfd.Session(None, dry_run=True, log=self.log), nullcontext()
        if self.product_id is None:
            raise DeviceError("profile has no product id; pass --pid")
        link = usbctl.UsbHid(self.vendor_id, self.product_id,
                             self.profile.lighting_interface or hfd.CONFIG_INTERFACE)
        return hfd.Session(link, log=self.log, trace=self.trace), link

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
        if not self.dry_run:
            _save_json(lighting_state_path(), {"effect": effect, "color": list(color), "brightness": brightness,
                                               "speed": speed, "rainbow": rainbow, "direction": direction})

    @staticmethod
    def saved_lighting() -> dict:
        """The lighting last applied by this tool, or {} if unknown."""
        return _load_json(lighting_state_path(), {})

    def set_key_colors(self, colors: dict[str, tuple[int, int, int]], default=(0, 0, 0),
                       brightness: int = 5) -> None:
        chosen = {self.profile.key(name).name: tuple(rgb) for name, rgb in colors.items()}
        table = {key.index: chosen.get(key.name, tuple(default)) for key in self.profile.keys}
        self._run(lambda s: s.set_key_colors(table, brightness=brightness))
        if not self.dry_run:
            _save_json(colors_state_path(), {"default": list(default),
                                             "keys": {k: list(v) for k, v in sorted(chosen.items())}})

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
        return _load_json(keymap_state_path(), {})

    def write_remaps(self, state: dict[str, str]) -> None:
        """Write the full base-layer table; keys not in *state* keep their default."""
        entries = {self.profile.key(name).index: hfd.key_entry(target) for name, target in state.items()}
        self._run(lambda s: s.write_keymap(entries))
        if not self.dry_run:
            _save_json(keymap_state_path(), state)

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

    def sync_time(self, when: datetime | None = None, save: bool = True) -> None:
        self._run(lambda s: s.sync_time(when, save=save))

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

    # ----------------------------------------------------------- diagnostics

    def diagnose(self) -> dict[str, tuple[bool | None, str]]:
        """Read-only health check: {item: (ok, text)}; ok is None when not applicable."""
        report: dict[str, tuple[bool | None, str]] = {}
        state = self.connection()
        report["connection"] = {
            "usb": (True, "USB cable (wired mode)"),
            "bluetooth": (False, "Bluetooth only: settings need the USB cable"),
            "none": (False, "Not found"),
        }[state]
        if state == "usb":
            try:
                import usb.core
                import usb.util

                dev = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
                version = dev.bcdDevice
                firmware = f"{version >> 8}.{version & 0xFF:02x}"
                try:
                    product = usb.util.get_string(dev, dev.iProduct)
                    firmware += f" ({product})"
                except Exception:  # needs access to the device node
                    pass
                report["firmware"] = (None, firmware)
            except Exception as exc:
                report["firmware"] = (None, f"unknown ({exc})")
            try:
                with usbctl.UsbHid(self.vendor_id, self.product_id, hfd.CONFIG_INTERFACE) as link:
                    descriptor = link.report_descriptor()
                ok = descriptor[:3] == b"\x06\x13\xff"
                report["config"] = (ok, "OK (interface 3)" if ok else "unexpected descriptor")
            except Exception as exc:
                report["config"] = (False, f"not accessible: {exc}")
            screen_ok = any(i.interface == hfd.SCREEN_INTERFACE
                            for i in enumerate_interfaces(self.vendor_id, self.product_id or 0))
            report["screen"] = (screen_ok, "OK (interface 2)" if screen_ok else "not accessible")
        rule = Path("/etc/udev/rules.d/70-infi75.rules")
        report["udev"] = (rule.exists(), "installed" if rule.exists() else "not installed")
        return report
