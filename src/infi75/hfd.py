"""Configuration protocol of the INFI75 (HFD RKGK890 / SONiX SN32F290).

Decoded from the INFI75 Driver V1.1 (DeviceDriver.exe) and cross-checked
against https://github.com/gohv/EPOMAKER-Ajazz-AK820-Pro, which drives the
same command set on the Ajazz AK820 Pro.

Every message is a 64-byte HID feature report (report ID 0) on the 0xFF13
interface, interface 3 on the INFI75. Commands start with 0x04; a
transaction is framed by START (04 18) and SAVE (04 02), optionally
followed by FINISH (04 f0). After an acknowledged command the keyboard
echoes it back on a feature read with byte 3 = 1.

The INFI75-1.2 firmware declares interface 3 without an IN endpoint, so
operating systems leave it without a HID driver. The reports are therefore
sent as raw USB control requests (see usbctl.py).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

PACKET = 64
CONFIG_INTERFACE = 3

START = 0x18
SAVE = 0x02
FINISH = 0xF0
MODE = 0x13
TIME = 0x28
KEYMAP = 0x11  # base layer

KEYMAP_PACKETS = 9  # announced in the KEYMAP header
KEYMAP_SENT = 10  # the vendor driver sends 0x2b6 >> 6 = 10 packets
KEYMAP_SLOTS = KEYMAP_PACKETS * PACKET // 4  # 144 four-byte entries

# Consumer-page usages the vendor driver offers for media keys.
MEDIA = {
    "playpause": 0xCD, "stop": 0xB7, "prev": 0xB6, "next": 0xB5,
    "volup": 0xE9, "voldown": 0xEA, "mute": 0xE2,
}
MODIFIER_BITS = {0xE0 + i: 1 << i for i in range(8)}

# Effect numbers, named after gohv/EPOMAKER-Ajazz-AK820-Pro and checked on
# an INFI75-1.2 (descriptions are what that keyboard showed).
EFFECTS = {
    "effect-0": (0x00, "fixed blue, ignores --color"),
    "static": (0x01, "steady colour"),
    "single-on": (0x02, "dark, keys light up when pressed"),
    "single-off": (0x03, "lit, keys go dark when pressed"),
    "glittering": (0x04, "dimmed colour"),
    "falling": (0x05, "rainfall, random blinking"),
    "colourful": (0x06, "random rainbow"),
    "breath": (0x07, "breathing"),
    "spectrum": (0x08, "colour rolling"),
    "outward": (0x09, "pulsing"),
    "scrolling": (0x0A, "pulsing"),
    "rolling": (0x0B, "faster pulsing"),
    "rotating": (0x0C, "pulsing"),
    "explode": (0x0D, "pulsing"),
    "launch": (0x0E, "pulse on key press"),
    "ripples": (0x0F, "faster pulse on key press"),
    "flowing": (0x10, "rows sweeping top to bottom, left to right"),
    "pulsating": (0x11, "twinkle running left to right"),
    "tilt": (0x12, "faster twinkle"),
    "shuttle": (0x13, "sweep right to left"),
}
MODES = {name: value for name, (value, _) in EFFECTS.items()}
# Effect 0 is not "off" on the INFI75; a dark keyboard is effect 2 at
# brightness 0, which is also what the AK820 tool sends.
OFF = (0x02, 0)

DIRECTIONS = {"left": 0, "down": 1, "up": 2, "right": 3}
MAX_LEVEL = 5  # brightness and speed run 0-5


class ProtocolError(ValueError):
    pass


class FeatureLink(Protocol):
    def set_feature(self, data: bytes, report_id: int = 0) -> int: ...
    def get_feature(self, report_id: int = 0, length: int = 64) -> bytes: ...


def command(cmd: int, byte2: int = 0, byte8: int = 0) -> bytes:
    packet = bytearray(PACKET)
    packet[0], packet[1], packet[2], packet[8] = 0x04, cmd, byte2, byte8
    return bytes(packet)


def resolve_mode(name_or_number: str) -> int:
    key = name_or_number.strip().lower()
    if key in MODES:
        return MODES[key]
    try:
        value = int(key, 0)
    except ValueError:
        raise ProtocolError(f"unknown effect {name_or_number!r}; known: {', '.join(MODES)}") from None
    if not 0 <= value <= 0xFF:
        raise ProtocolError("effect number must be 0-255")
    return value


@dataclass(frozen=True)
class Lighting:
    mode: int
    color: tuple[int, int, int] = (255, 255, 255)
    rainbow: bool = False
    brightness: int = 5
    speed: int = 3
    direction: int = 0


def lighting_data(settings: Lighting) -> bytes:
    if not 0 <= settings.brightness <= MAX_LEVEL or not 0 <= settings.speed <= MAX_LEVEL:
        raise ProtocolError(f"brightness and speed must be 0-{MAX_LEVEL}")
    r, g, b = settings.color
    packet = bytearray(PACKET)
    packet[0] = settings.mode
    packet[1:4] = bytes((r, g, b))
    packet[8] = 1 if settings.rainbow else 0
    packet[9] = settings.brightness
    packet[10] = settings.speed
    packet[11] = settings.direction
    packet[14:16] = b"\xaa\x55"
    return bytes(packet)


def time_data(when: datetime, profile: int = 0) -> bytes:
    packet = bytearray(PACKET)
    packet[1] = profile + 1
    packet[2] = 0x5A
    packet[3] = when.year % 2000
    packet[4:9] = bytes((when.month, when.day, when.hour, when.minute, when.second))
    packet[62:64] = b"\xaa\x55"
    return bytes(packet)


def key_entry(target: str) -> bytes:
    """Encode a remap target as the firmware's 4-byte key action.

    Keyboard keys: [02, modifier bits, HID usage, 00], e.g. "ctrl+c".
    A modifier on its own: [02, bit, 00, 00]. Media keys: [03, usage lo, usage hi, 00].
    "default" gives 00 00 00 00, which keeps the key's built-in function.
    """
    from . import hidkeys

    spec = target.strip().lower()
    if spec in ("default", "reset"):
        return bytes(4)
    if spec in MEDIA:
        usage = MEDIA[spec]
        return bytes((0x03, usage & 0xFF, usage >> 8, 0))
    parts = [p for p in spec.split("+") if p]
    if not parts:
        raise ProtocolError("empty remap target")
    codes = [hidkeys.code(p) for p in parts]
    mods = 0
    for c in codes[:-1]:
        if c not in MODIFIER_BITS:
            raise ProtocolError(f"{target!r}: only the last part of a combination may be a non-modifier key")
        mods |= MODIFIER_BITS[c]
    last = codes[-1]
    if last in MODIFIER_BITS:
        return bytes((0x02, mods | MODIFIER_BITS[last], 0, 0))
    return bytes((0x02, mods, last, 0))


def keymap_payload(entries: dict[int, bytes]) -> bytes:
    """Base-layer table: 4 bytes per key slot, zero = keep default."""
    buf = bytearray(KEYMAP_SENT * PACKET)
    for slot, entry in entries.items():
        if not 0 < slot < KEYMAP_SLOTS or len(entry) != 4:
            raise ProtocolError(f"invalid key slot {slot}")
        buf[slot * 4 : slot * 4 + 4] = entry
    buf[KEYMAP_PACKETS * PACKET - 2 : KEYMAP_PACKETS * PACKET] = b"\xaa\x55"
    return bytes(buf)


class Session:
    """Sends packets with the vendor driver's pacing and acknowledgement checks."""

    def __init__(self, link: FeatureLink | None, dry_run: bool = False,
                 log: Callable[[str], None] | None = None, delay: float = 0.01,
                 busy_polls: int = 150, busy_delay: float = 0.02) -> None:
        self.link = link
        self.dry_run = dry_run
        self.log = log or (lambda msg: print(msg, file=sys.stderr))
        self.delay = delay
        self.busy_polls = busy_polls
        self.busy_delay = busy_delay

    def send(self, packet: bytes, ack: bool = True) -> None:
        if self.dry_run or self.link is None:
            self.log(f"[dry-run if={CONFIG_INTERFACE} feature] {packet.hex(' ')}")
            return
        written = self.link.set_feature(packet)
        if written != len(packet):
            raise ProtocolError(f"keyboard accepted {written} of {len(packet)} bytes")
        time.sleep(self.delay)
        if not ack:
            return
        # Commands (04 xx) are echoed with a status in byte 3: 1 = done,
        # 0xff = busy (seen on SAVE while it writes flash). Data packets are
        # echoed verbatim. The vendor driver ignores the outcome, so a
        # missing confirmation is reported but does not abort.
        reply = self.link.get_feature(0, PACKET)
        if packet[0] != 0x04:
            return
        for _ in range(self.busy_polls):
            if len(reply) > 3 and reply[3] != 0xFF:
                break
            time.sleep(self.busy_delay)
            reply = self.link.get_feature(0, PACKET)
        if len(reply) < 4 or reply[3] not in (0, 1):
            self.log(f"warning: no confirmation for {packet[:2].hex(' ')}: reply {bytes(reply[:8]).hex(' ')}")

    def set_lighting(self, settings: Lighting) -> None:
        self.send(command(START))
        self.send(command(MODE, byte8=1))
        self.send(lighting_data(settings), ack=False)
        self.send(command(SAVE))
        self.send(command(FINISH))

    def write_keymap(self, entries: dict[int, bytes]) -> None:
        """Replace the base-layer remaps; slots not in *entries* return to default."""
        payload = keymap_payload(entries)
        self.send(command(START))
        self.send(command(KEYMAP, byte8=KEYMAP_PACKETS))
        for offset in range(0, len(payload), PACKET):
            self.send(payload[offset : offset + PACKET], ack=False)
        self.send(command(SAVE))
        self.send(command(FINISH))

    def sync_time(self, when: datetime | None = None) -> None:
        self.send(command(START))
        self.send(command(TIME, byte8=1))
        self.send(time_data(when or datetime.now()))
        self.send(command(SAVE))
