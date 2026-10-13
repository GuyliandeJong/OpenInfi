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

from . import hfd, macro, screen, usbctl
from .profile import Profile
from .transport import DeviceError, _hid, enumerate_interfaces


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    folder = base / "openinfi"
    legacy = base / "infi75"  # the project's former name
    if not folder.exists() and legacy.is_dir():
        try:
            legacy.rename(folder)
        except OSError:
            return legacy
    return folder


LAYERS = {"base": hfd.KEYMAP, "fn": hfd.FN_KEYMAP}


def keymap_state_path(layer: str = "base") -> Path:
    return config_dir() / ("keymap.json" if layer == "base" else f"keymap-{layer}.json")


def system_state_path() -> Path:
    return config_dir() / "system.json"


def macros_state_path() -> Path:
    return config_dir() / "macros.json"


def screen_state_path() -> Path:
    return config_dir() / "screen.json"


def setups_dir() -> Path:
    return config_dir() / "setups"


def _slug(name: str) -> str:
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("a setup needs a name")
    return slug


def colors_state_path() -> Path:
    return config_dir() / "colors.json"


def lighting_state_path() -> Path:
    return config_dir() / "lighting.json"


# state files that together describe everything this tool has written to the keyboard
SETUP_PARTS = {
    "lighting": lighting_state_path,
    "colors": colors_state_path,
    "keymap": lambda: keymap_state_path("base"),
    "keymap_fn": lambda: keymap_state_path("fn"),
    "system": system_state_path,
    "macros": macros_state_path,
    "screen": screen_state_path,
}


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
                                               "speed": speed, "rainbow": rainbow, "direction": direction,
                                               "custom": False})

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
            _save_json(colors_state_path(), {"default": list(default), "brightness": brightness,
                                             "keys": {k: list(v) for k, v in sorted(chosen.items())}})
            # the keyboard now shows the custom colours instead of the effect
            lighting = self.saved_lighting()
            lighting["custom"] = True
            _save_json(lighting_state_path(), lighting)

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

    @staticmethod
    def _layer(layer: str) -> int:
        try:
            return LAYERS[layer]
        except KeyError:
            raise ValueError(f"unknown layer {layer!r}; use 'base' or 'fn'") from None

    def remaps(self, layer: str = "base") -> dict[str, str]:
        self._layer(layer)
        return _load_json(keymap_state_path(layer), {})

    def write_remaps(self, state: dict[str, str], layer: str = "base") -> None:
        """Write one layer's full table; keys not in *state* keep their default."""
        command = self._layer(layer)
        entries = {}
        for name, target in state.items():
            key = self.profile.key(name)
            if layer == "fn" and not key.fn:
                raise ValueError(f"Fn + {key.name} is reserved by the keyboard and cannot be remapped")
            entries[key.index] = hfd.key_entry(self._resolve_macro(target))
        self._run(lambda s: s.write_keymap(entries, command))
        if not self.dry_run:
            _save_json(keymap_state_path(layer), state)

    def remap(self, key_name: str, target: str, layer: str = "base") -> dict[str, str]:
        key = self.profile.key(key_name)
        hfd.key_entry(self._resolve_macro(target))  # validate before storing
        state = self.remaps(layer)
        if target.strip().lower() in ("default", "reset"):
            state.pop(key.name, None)
        else:
            state[key.name] = target
        self.write_remaps(state, layer)
        return state

    def reset_remaps(self, layer: str = "base") -> None:
        self.write_remaps({}, layer)

    def read_key_colors(self) -> dict[str, tuple[int, int, int]]:
        """Live LED colours by key name (experimental, see hfd.Session.read_key_colors)."""
        result: dict[int, tuple[int, int, int]] = {}

        def action(session) -> None:
            result.update(session.read_key_colors())

        self._run(action)
        by_slot = {k.index: k.name for k in self.profile.keys}
        return {by_slot[slot]: rgb for slot, rgb in result.items() if slot in by_slot}

    def replay(self, packets: list[bytes]) -> int:
        """Send raw 64-byte configuration packets, e.g. from a capture of the vendor driver."""
        for packet in packets:
            if len(packet) != hfd.PACKET:
                raise ValueError(f"packets must be {hfd.PACKET} bytes")
        self._run(lambda s: [s.send(p, ack=p[0] == 0x04) for p in packets])
        return len(packets)

    # -------------------------------------------------------------- macros

    @staticmethod
    def macros() -> list[dict]:
        """Saved macros in table order: [{"name": ..., "sequence": ...}]."""
        return _load_json(macros_state_path(), [])

    def _macro_ref(self, target: str) -> tuple[int, int] | None:
        """(table index, repeat count) for 'macro:NAME' / 'macro:NAMExCOUNT', None for other targets."""
        spec = target.strip()
        if not spec.lower().startswith("macro:"):
            return None
        names = [m["name"].lower() for m in self.macros()]
        name, count = spec[6:], "1"
        if name.lower() not in names:  # names may contain an x, so try the exact name first
            head, sep, tail = name.rpartition("x")
            if sep and tail.isdigit():
                name, count = head, tail
        if name.lower() not in names:
            raise ValueError(f"no macro named {name!r}; 'openinfi macro list' shows them")
        return names.index(name.lower()), int(count)

    def _resolve_macro(self, target: str) -> str:
        """'macro:NAME[xCOUNT]' -> 'macro:INDEXxCOUNT' for hfd.key_entry; other targets unchanged."""
        ref = self._macro_ref(target)
        return target if ref is None else f"macro:{ref[0]}x{ref[1]}"

    def write_macros(self, macros: list[dict]) -> None:
        events = [macro.parse(m["sequence"]) for m in macros]
        names = [m["name"].lower() for m in macros]
        if len(set(names)) != len(names):
            raise ValueError("macro names must be unique")
        self._run(lambda s: s.write_macros(events))
        if not self.dry_run:
            _save_json(macros_state_path(), macros)

    def save_macro(self, name: str, sequence: str) -> list[dict]:
        """Add a macro, or replace the one with the same name; writes the whole table."""
        name = name.strip()
        if not name or ":" in name:
            raise ValueError("a macro needs a name without ':'")
        macro.parse(sequence)  # validate before writing
        macros = self.macros()
        for item in macros:
            if item["name"].lower() == name.lower():
                item.update(name=name, sequence=sequence)
                break
        else:
            macros.append({"name": name, "sequence": sequence})
        self.write_macros(macros)
        return macros

    def delete_macro(self, name: str) -> list[dict]:
        macros = self.macros()
        names = [m["name"].lower() for m in macros]
        if name.strip().lower() not in names:
            raise ValueError(f"no macro named {name!r}")
        index = names.index(name.strip().lower())
        users = [f"{'Fn+' if layer == 'fn' else ''}{key}" for layer in LAYERS
                 for key, target in self.remaps(layer).items()
                 if (ref := self._macro_ref(target)) is not None and ref[0] == index]
        if users:
            raise ValueError(f"macro {name!r} is used by {', '.join(users)}; restore those keys first")
        remaining = macros[:index] + macros[index + 1:]
        self.write_macros(remaining)
        # remaps point at table positions, which shifted: rewrite layers that use macros
        for layer in LAYERS:
            state = self.remaps(layer)
            if any(t.lower().startswith("macro:") for t in state.values()):
                self.write_remaps(state, layer)
        return remaining

    # -------------------------------------------------------------- system

    def system(self) -> hfd.System:
        saved = _load_json(system_state_path(), {})
        fields = hfd.System.__dataclass_fields__
        return hfd.System(**{k: v for k, v in saved.items() if k in fields})

    def set_system(self, **changes) -> hfd.System:
        """Change some of game mode, key blocking and sleep; the rest keep their last written value."""
        from dataclasses import asdict, replace

        settings = replace(self.system(), **changes)
        hfd.system_data(settings)  # validate
        self._run(lambda s: s.set_system(settings))
        if not self.dry_run:
            _save_json(system_state_path(), asdict(settings))
        return settings

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
        _save_json(screen_state_path(), {"path": str(Path(path).absolute()), "fit": fit, "slot": slot})
        return len(frames)

    # -------------------------------------------------------------- setups

    @staticmethod
    def setups() -> list[str]:
        """Names of the saved setups, sorted."""
        names = []
        for path in sorted(setups_dir().glob("*.json")):
            data = _load_json(path, {})
            names.append(data.get("name", path.stem))
        return sorted(names, key=str.lower)

    @staticmethod
    def save_setup(name: str) -> Path:
        """Snapshot what this tool last wrote to the keyboard under *name* (replaces a setup of that name)."""
        parts = {}
        for part, path in SETUP_PARTS.items():
            data = _load_json(path(), None)
            if data:
                parts[part] = data
        if not parts:
            raise ValueError("nothing to save yet: apply some settings to the keyboard first")
        target = setups_dir() / f"{_slug(name)}.json"
        _save_json(target, {"name": name.strip(), "saved": datetime.now().isoformat(timespec="seconds"),
                            "parts": parts})
        return target

    @staticmethod
    def load_setup(name: str) -> dict:
        path = setups_dir() / f"{_slug(name)}.json"
        data = _load_json(path, None)
        if not data:
            raise ValueError(f"no setup named {name!r}")
        return data

    @staticmethod
    def delete_setup(name: str) -> None:
        path = setups_dir() / f"{_slug(name)}.json"
        if not path.exists():
            raise ValueError(f"no setup named {name!r}")
        path.unlink()

    def apply_setup(self, name: str, include_screen: bool = True,
                    progress: Callable[[int, int], None] | None = None) -> list[str]:
        """Write a saved setup to the keyboard. Returns what was applied."""
        parts = self.load_setup(name)["parts"]
        done = []
        if "macros" in parts:
            self.write_macros(parts["macros"])
            done.append("macros")
        if "system" in parts:
            fields = hfd.System.__dataclass_fields__
            self.set_system(**{k: v for k, v in parts["system"].items() if k in fields})
            done.append("game mode and sleep")
        self.write_remaps(parts.get("keymap", {}), "base")
        self.write_remaps(parts.get("keymap_fn", {}), "fn")
        done.append("remaps")
        lighting = parts.get("lighting", {})
        colors = parts.get("colors")
        if lighting.get("custom") and colors:
            self.set_key_colors({k: tuple(v) for k, v in colors.get("keys", {}).items()},
                                default=tuple(colors.get("default", (0, 0, 0))),
                                brightness=int(colors.get("brightness", lighting.get("brightness", 5))))
            if not self.dry_run:  # keep the effect settings of the setup for the lighting page
                _save_json(lighting_state_path(), lighting)
            done.append("key colours")
        elif lighting:
            self.set_lighting(lighting.get("effect", "static"), tuple(lighting.get("color", (255, 255, 255))),
                              int(lighting.get("brightness", 5)), int(lighting.get("speed", 3)),
                              bool(lighting.get("rainbow", False)), lighting.get("direction", "right"))
            if colors and not self.dry_run:
                _save_json(colors_state_path(), colors)
            done.append("lighting")
        picture = parts.get("screen")
        if include_screen and picture and Path(picture.get("path", "")).is_file():
            self.upload_image(picture["path"], fit=picture.get("fit", "crop"), slot=int(picture.get("slot", 1)),
                              progress=progress)
            done.append("screen picture")
        return done

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
        rule = Path("/etc/udev/rules.d/70-openinfi.rules")
        legacy = Path("/etc/udev/rules.d/70-infi75.rules")
        if rule.exists() or Path("/usr/lib/udev/rules.d/70-openinfi.rules").exists():
            report["udev"] = (True, "installed")
        elif legacy.exists():
            report["udev"] = (False, "old version (70-infi75.rules): reinstall it")
        else:
            report["udev"] = (False, "not installed")
        return report
