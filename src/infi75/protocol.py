"""Packet builders for the Royuan (USB VID 0x3151) keyboard protocol family.

All functions are pure: they return the exact report bytes to send, which
keeps them testable without hardware and lets ``--dry-run`` show them.

The layouts below were reverse-engineered for the Epomaker RT100 by the
epomaker-controller project (https://github.com/strodgers/epomaker-controller)
and OpenRGB's EpomakerController. The INFI75 ships with a driver from the
same vendor ecosystem, but whether it speaks this exact dialect is not
confirmed. Verify against a capture of the official software
(see ``infi75 capture``) before relying on any command.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum

PAYLOAD_PER_PACKET = 56  # 64-byte report minus 8-byte header
SCREEN_PAYLOAD_PER_PACKET = 56


class Mode(IntEnum):
    STATIC = 0x01
    BREATHING = 0x02
    SPECTRUM = 0x03
    DRIFT = 0x04
    RIPPLE = 0x05
    TWINKLE = 0x06
    STREAM = 0x07
    SHADOWING = 0x08
    PEAKS = 0x09
    SINE_WAVE = 0x0A
    SURGING = 0x0B
    BLOOMING = 0x0C
    LASER = 0x0E
    PEAK_TURN = 0x0F
    RAIN = 0x10
    SNOW = 0x11
    METEOR = 0x12
    SNOW_TRACE = 0x13
    LIGHT_SHADOW = 0x15


class Direction(IntEnum):
    """Direction modifier for DRIFT (others reuse the same high nibble)."""

    RIGHT = 0x00
    LEFT = 0x10
    DOWN = 0x20
    UP = 0x30


SPEED_RANGE = range(0, 6)
BRIGHTNESS_RANGE = range(0, 5)
_DAZZLE_OFF, _DAZZLE_ON = 0x07, 0x08


def checksum(data: bytes) -> int:
    """Vendor checksum: 0xFF minus the low byte of the byte sum."""
    return (0xFF - (sum(data) & 0xFF)) & 0xFF


def _pad(data: bytes | bytearray, size: int) -> bytes:
    if len(data) > size:
        raise ValueError(f"packet is {len(data)} bytes, limit {size}")
    return bytes(data) + bytes(size - len(data))


def _header(*values: int) -> bytes:
    """Seven header bytes followed by their checksum."""
    head = bytes(values)
    if len(head) != 7:
        raise ValueError("header must be 7 bytes before the checksum")
    return head + bytes([checksum(head)])


def _rgb(color: tuple[int, int, int]) -> tuple[int, int, int]:
    if len(color) != 3 or not all(0 <= c <= 255 for c in color):
        raise ValueError(f"invalid RGB colour {color!r}")
    return tuple(color)  # type: ignore[return-value]


@dataclass(frozen=True)
class Lighting:
    mode: Mode = Mode.STATIC
    color: tuple[int, int, int] = (255, 255, 255)
    speed: int = 3
    brightness: int = 4
    rainbow: bool = False  # "dazzle": cycle colours instead of using `color`
    direction: Direction = Direction.RIGHT


def lighting(settings: Lighting, size: int = 64) -> list[bytes]:
    """Global lighting effect, colour, speed and brightness."""
    if settings.speed not in SPEED_RANGE:
        raise ValueError(f"speed must be {SPEED_RANGE.start}-{SPEED_RANGE.stop - 1}")
    if settings.brightness not in BRIGHTNESS_RANGE:
        raise ValueError(f"brightness must be {BRIGHTNESS_RANGE.start}-{BRIGHTNESS_RANGE.stop - 1}")
    r, g, b = _rgb(settings.color)
    option = int(settings.direction) | (_DAZZLE_ON if settings.rainbow else _DAZZLE_OFF)
    body = bytes([0x07, int(settings.mode), settings.speed, settings.brightness, option, r, g, b])
    return [_pad(body + bytes([checksum(body)]), size)]


def key_colors(
    colors: dict[int, tuple[int, int, int]],
    slots: int = 130,
    frame_time: int = 0,
    size: int = 64,
) -> list[bytes]:
    """Per-key static colours. *colors* maps firmware key index to RGB.

    Keys absent from *colors* are switched off.
    """
    buffer = bytearray(slots * 3)
    for index, color in colors.items():
        if not 0 <= index < slots:
            raise ValueError(f"key index {index} outside 0-{slots - 1}")
        buffer[index * 3 : index * 3 + 3] = bytes(_rgb(color))
    count = -(-len(buffer) // PAYLOAD_PER_PACKET)
    packets = [_pad(bytes.fromhex("18000000000000e7"), size)]
    for n in range(count):
        chunk = buffer[n * PAYLOAD_PER_PACKET : (n + 1) * PAYLOAD_PER_PACKET]
        packets.append(_pad(_header(0x19, n, 0, 1, frame_time, 0, 0) + chunk, size))
    return packets


def remap(key_index: int, hid_code: int, size: int = 64) -> list[bytes]:
    """Make the physical key at *key_index* send USB HID usage *hid_code*."""
    if not 0 <= key_index <= 0xFF or not 0 <= hid_code <= 0xFF:
        raise ValueError("key index and HID code must fit in one byte")
    return [_pad(_header(0x13, 0, key_index, 0, 0, 0, 0) + bytes([0, 0, hid_code]), size)]


def set_time(when: datetime, size: int = 64) -> list[bytes]:
    """Set the clock shown on the screen."""
    body = _header(0x28, 0, 0, 0, 0, 0, 0) + when.year.to_bytes(2, "big")
    body += bytes([when.month, when.day, when.hour, when.minute, when.second])
    return [_pad(body, size)]


def screen_image(pixels: bytes, size: int = 64) -> list[bytes]:
    """Upload a raw RGB565 (big-endian) frame to the screen.

    The start packet carries the total byte length (24-bit little-endian);
    each data packet carries a 16-bit little-endian sequence number and its
    payload length.
    """
    total = len(pixels)
    if total == 0 or total % 2:
        raise ValueError("pixel data must be a non-empty RGB565 buffer")
    if total >= 1 << 24:
        raise ValueError("image too large")
    start = _header(0xA5, 0x00, 0x01, 0x00, *total.to_bytes(3, "little"))
    # The trailing four bytes are copied verbatim from RT100 captures; their
    # meaning is unknown.
    packets = [_pad(start + bytes.fromhex("0000a2ad"), size)]
    for seq, offset in enumerate(range(0, total, SCREEN_PAYLOAD_PER_PACKET)):
        chunk = pixels[offset : offset + SCREEN_PAYLOAD_PER_PACKET]
        head = _header(0x25, 0x00, 0x01, 0x00, *seq.to_bytes(2, "little"), len(chunk))
        packets.append(_pad(head + chunk, size))
    return packets


ONLINE_COMMANDS = {
    1: "COMMUNICATION_START", 2: "COMMUNICATION_END", 15: "SET_FACTORY_RESET", 16: "GET_DEVICE_INFO",
    17: "GET_GAME_MODE", 18: "GET_KEY", 19: "GET_LED_EFFECT", 20: "GET_CUSTOM_LED_DATA", 21: "GET_MACRO",
    22: "GET_FN_KEY", 28: "GET_DEFAULT_FN_KEY_MATRIX", 31: "GET_DEFAULT_KEY_MATRIX", 33: "SET_GAME_MODE",
    34: "SET_KEY", 35: "SET_LED_EFFECT", 36: "SET_CUSTOM_LED_DATA", 37: "SET_MACRO", 38: "SET_FN_KEY",
    52: "SET_TEMPORARY_COMMAND_DATA", 64: "SET_LED_BOOT_ANIMATION", 65: "SET_LED_USER_ANIMATION",
    80: "SET_TFT_USER_ANIMATION", 81: "SET_TFT_BUILT_IN_INDEX",
}


def describe(packet: bytes) -> str:
    """Best-effort human description of a packet (Royuan or AJAZZ/HFD "online" framing)."""
    if not packet:
        return "empty"
    op = packet[0]
    if op in (0xAA, 0x55) and len(packet) >= 8:
        direction = "request" if op == 0xAA else "reply"
        name = ONLINE_COMMANDS.get(packet[1], f"cmd 0x{packet[1]:02x}")
        addr = packet[3] | (packet[4] << 8)
        return f"online {direction} {name} len={packet[2]} addr={addr} last={packet[6]}"
    if op == 0x07 and len(packet) >= 9:
        try:
            mode = Mode(packet[1]).name
        except ValueError:
            mode = f"0x{packet[1]:02x}"
        return (
            f"lighting mode={mode} speed={packet[2]} brightness={packet[3]} "
            f"option=0x{packet[4]:02x} rgb=({packet[5]},{packet[6]},{packet[7]})"
        )
    if op == 0x18:
        return "per-key colour: begin"
    if op == 0x19:
        return f"per-key colour: data #{packet[1]} frame={packet[2]}/{packet[3]}"
    if op == 0x13 and len(packet) >= 11:
        return f"remap key index={packet[2]} -> HID 0x{packet[10]:02x}"
    if op == 0x28 and len(packet) >= 15:
        year = int.from_bytes(packet[8:10], "big")
        return "set time {}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(year, *packet[10:15])
    if op == 0xA5 and len(packet) >= 7:
        total = int.from_bytes(packet[4:7], "little")
        return f"screen upload: begin, {total} bytes ({total // 2} RGB565 pixels)"
    if op == 0x25 and len(packet) >= 7:
        return f"screen upload: data seq={int.from_bytes(packet[4:6], 'little')} len={packet[6]}"
    return f"unknown opcode 0x{op:02x}"
