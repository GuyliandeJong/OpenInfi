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

# Effect numbers as used by the AK820 Pro firmware family; names follow
# gohv/EPOMAKER-Ajazz-AK820-Pro. Verify each on the INFI75.
MODES = {
    "off": 0x00, "static": 0x01, "single-on": 0x02, "single-off": 0x03, "glittering": 0x04,
    "falling": 0x05, "colourful": 0x06, "breath": 0x07, "spectrum": 0x08, "outward": 0x09,
    "scrolling": 0x0A, "rolling": 0x0B, "rotating": 0x0C, "explode": 0x0D, "launch": 0x0E,
    "ripples": 0x0F, "flowing": 0x10, "pulsating": 0x11, "tilt": 0x12, "shuttle": 0x13,
}
DIRECTIONS = {"left": 0, "down": 1, "up": 2, "right": 3}
MAX_LEVEL = 5  # brightness and speed run 0-5


class ProtocolError(RuntimeError):
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


class Session:
    """Sends packets with the vendor driver's pacing and acknowledgement checks."""

    def __init__(self, link: FeatureLink | None, dry_run: bool = False,
                 log: Callable[[str], None] | None = None, delay: float = 0.01) -> None:
        self.link = link
        self.dry_run = dry_run
        self.log = log or (lambda msg: print(msg, file=sys.stderr))
        self.delay = delay

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
        # The vendor driver reads the status from byte 3 of the echo:
        # 1 = done, 0xff = busy (it resends once), anything else = failure.
        for attempt in range(2):
            reply = self.link.get_feature(0, PACKET)
            status = reply[3] if len(reply) > 3 else None
            if status == 1:
                return
            if status == 0xFF and attempt == 0:
                time.sleep(self.delay)
                self.link.set_feature(packet)
                time.sleep(self.delay)
                continue
            break
        raise ProtocolError(
            f"keyboard did not confirm {packet[:2].hex(' ')}: reply {bytes(reply[:8]).hex(' ')}"
        )

    def set_lighting(self, settings: Lighting) -> None:
        self.send(command(START))
        self.send(command(MODE, byte8=1))
        self.send(lighting_data(settings), ack=False)
        self.send(command(SAVE))
        self.send(command(FINISH))

    def sync_time(self, when: datetime | None = None) -> None:
        self.send(command(START))
        self.send(command(TIME, byte8=1))
        self.send(time_data(when or datetime.now()))
        self.send(command(SAVE))
