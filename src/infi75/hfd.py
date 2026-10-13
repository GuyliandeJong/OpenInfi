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
FN_KEYMAP = 0x27  # what a key does while Fn is held; same table layout
SYSTEM = 0x17  # game mode, Windows-key lock and sleep timer, one data packet
READ_LEDS = 0xF5  # live per-key LED state; byte 8 = reports to read (9 colour, 3 brightness)
MACRO_BEGIN = 0x19  # sent on its own before a macro upload
MACROS = 0x15  # macro table: byte 8 = packets announced
KEY_COLORS_PREVIEW = 0x20  # live preview only; the stored custom colours return
KEY_COLORS = 0x23  # stored custom colours shown by CUSTOM_MODE

CUSTOM_MODE = 0x80
KEY_COLOR_PACKETS = 9  # 144 slot-indexed entries of [slot, R, G, B], aa 55 at 574

SCREEN = 0x72
SCREEN_WIDTH, SCREEN_HEIGHT = 135, 240  # portrait, row-major, RGB565 little-endian
SCREEN_FRAME = SCREEN_WIDTH * SCREEN_HEIGHT * 2  # 0xfd20
SCREEN_HEADER = 0x100
SCREEN_CHUNK = 0x1000  # one output report on the 0xFF68 interface
SCREEN_MAX_FRAMES = 0x8D
SCREEN_INTERFACE = 2

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


COMMAND_NAMES = {START: "start", SAVE: "save", FINISH: "finish", MODE: "lighting", TIME: "clock",
                 KEYMAP: "keymap", FN_KEYMAP: "Fn keymap", SYSTEM: "game mode/sleep", MACRO_BEGIN: "macro begin",
                 MACROS: "macros", KEY_COLORS_PREVIEW: "key colour preview", KEY_COLORS: "key colours",
                 SCREEN: "screen", READ_LEDS: "read LEDs"}


def describe(packet: bytes) -> str:
    """Short description of a captured configuration packet, for 'infi75 capture analyze'."""
    if not packet:
        return "empty"
    if packet[0] == 0x04 and len(packet) > 1:
        name = COMMAND_NAMES.get(packet[1], f"command 0x{packet[1]:02x}")
        extra = f", {packet[8]} data packet(s)" if len(packet) > 8 and packet[8] else ""
        status = f", status {packet[3]:02x}" if len(packet) > 3 and packet[3] else ""
        return f"{name}{extra}{status}"
    if len(packet) >= 16 and packet[14:16] == b"\xaa\x55":
        return f"lighting data: effect 0x{packet[0]:02x} rgb=({packet[1]},{packet[2]},{packet[3]})"
    return "data"


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
    Macros: "macro:N" or "macro:NxCOUNT" (N = 0-based table index) gives [06, N, mode 1, COUNT].
    """
    from . import hidkeys

    spec = target.strip().lower()
    if spec in ("default", "reset"):
        return bytes(4)
    if spec.startswith("macro:"):
        index, _, count = spec[6:].partition("x")
        try:
            index_n, count_n = int(index), int(count or 1)
        except ValueError:
            raise ProtocolError(f"{target!r}: use macro:INDEX or macro:INDEXxCOUNT") from None
        if not 0 <= index_n < MACRO_SLOTS or not 1 <= count_n <= 255:
            raise ProtocolError(f"{target!r}: macro index 0-{MACRO_SLOTS - 1}, count 1-255")
        return bytes((0x06, index_n, MACRO_MODES["times"], count_n))
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


MACRO_SLOTS = 100  # 4-byte offset entries in front of the macro data
MACRO_HEADER = MACRO_SLOTS * 4
MACRO_BUFFER = 0xE00  # the vendor driver's buffer
MACRO_DEFAULT_GAP_MS = 10  # inserted by the vendor driver between two non-delay events
# event flags in byte 3; byte 2 carries the HID usage or mouse button
MACRO_KEY_DOWN, MACRO_KEY_UP = 0xB0, 0x30
MACRO_MOUSE_DOWN, MACRO_MOUSE_UP = 0x90, 0x10
MACRO_DELAY = 0x50
MOUSE_BUTTONS = {1: 0x01, 2: 0x04, 3: 0x02}  # vendor list order left, right(?), middle(?) -> wire value
MACRO_MODES = {"times": 1}  # keymap entry byte 2; only the repeat-count mode is assumed so far


def macro_event(kind: str, value: int) -> bytes:
    if kind == "delay":
        if not 0 <= value <= 0xFFFF:
            raise ProtocolError(f"delay {value} ms out of range 0-65535")
        return bytes((value & 0xFF, value >> 8, 0, MACRO_DELAY))
    flag = {"down": MACRO_KEY_DOWN, "up": MACRO_KEY_UP,
            "mouse_down": MACRO_MOUSE_DOWN, "mouse_up": MACRO_MOUSE_UP}.get(kind)
    if flag is None:
        raise ProtocolError(f"unknown macro event {kind!r}")
    if kind.startswith("mouse"):
        if value not in MOUSE_BUTTONS:
            raise ProtocolError(f"mouse button must be 1-3, got {value}")
        value = MOUSE_BUTTONS[value]
    return bytes((0, 0, value & 0xFF, flag))


def macro_payload(macros: list[list[tuple[str, int]]]) -> tuple[int, bytes]:
    """Macro table as the vendor driver builds it. Returns (packets announced, bytes to send).

    Layout: 100 entries of 4 bytes (little-endian offset of the macro, ff ff ff ff when empty), then per
    macro an 8-byte header (event count, little-endian, in bytes 0-1) and its 4-byte events. The buffer
    is padded to whole packets plus one, with aa 55 in its last two bytes; one more zero packet follows.
    """
    if len(macros) > MACRO_SLOTS:
        raise ProtocolError(f"at most {MACRO_SLOTS} macros")
    buf = bytearray(MACRO_BUFFER)
    end = MACRO_HEADER
    for n, events in enumerate(macros):
        if not events:
            buf[n * 4 : n * 4 + 4] = b"\xff\xff\xff\xff"
            continue
        buf[n * 4 : n * 4 + 2] = end.to_bytes(2, "little")
        encoded: list[bytes] = []
        last_was_delay = False
        for kind, value in events:
            if kind != "delay" and encoded and not last_was_delay:
                encoded.append(macro_event("delay", MACRO_DEFAULT_GAP_MS))
            encoded.append(macro_event(kind, value))
            last_was_delay = kind == "delay"
        size = 8 + 4 * len(encoded)
        if end + size + 2 * PACKET > MACRO_BUFFER:
            raise ProtocolError("macros too long for the keyboard's macro memory")
        buf[end : end + 2] = len(encoded).to_bytes(2, "little")
        buf[end + 8 : end + size] = b"".join(encoded)
        end += size
    packets = -(-end // PACKET) + 1
    buf[packets * PACKET - 2 : packets * PACKET] = b"\xaa\x55"
    return packets, bytes(buf[: (packets + 1) * PACKET])


def keymap_payload(entries: dict[int, bytes]) -> bytes:
    """Keymap table (base or Fn layer): 4 bytes per key slot, zero = keep default."""
    buf = bytearray(KEYMAP_SENT * PACKET)
    for slot, entry in entries.items():
        if not 0 < slot < KEYMAP_SLOTS or len(entry) != 4:
            raise ProtocolError(f"invalid key slot {slot}")
        buf[slot * 4 : slot * 4 + 4] = entry
    buf[KEYMAP_PACKETS * PACKET - 2 : KEYMAP_PACKETS * PACKET] = b"\xaa\x55"
    return bytes(buf)


@dataclass
class System:
    """The 04 17 packet: the vendor driver always sends all of these together."""

    game_mode: bool = False
    block_alt_tab: bool = False  # only applied while game mode is on
    block_alt_f4: bool = False
    block_win: bool = False
    sleep: int = 2  # vendor list entries 1-5, default 2; durations not confirmed
    layer_flag: bool = False  # byte 5, from a two-way layer switch in the vendor UI; meaning unknown
    sleep_light: int = 0  # byte 6, "sleep_light" in the vendor profile, default 0; meaning unknown


SLEEP_CHOICES = range(1, 6)


def system_data(settings: System) -> bytes:
    if settings.sleep not in SLEEP_CHOICES:
        raise ProtocolError(f"sleep must be 1-5, got {settings.sleep}")
    packet = bytearray(PACKET)
    if settings.game_mode:
        packet[1] = 1
        packet[2] = int(settings.block_alt_tab)
        packet[3] = int(settings.block_alt_f4)
        packet[4] = int(settings.block_win)
    packet[5] = int(settings.layer_flag)
    packet[6] = settings.sleep_light & 0xFF
    packet[8] = settings.sleep
    packet[62:64] = b"\xaa\x55"
    return bytes(packet)


def key_colors_payload(colors: dict[int, tuple[int, int, int]]) -> bytes:
    """Slot-indexed table: entry n is [n, R, G, B]; aa 55 closes it at bytes 574-575."""
    size = KEY_COLOR_PACKETS * PACKET
    buf = bytearray(size)
    for slot, (r, g, b) in colors.items():
        if not 0 < slot < size // 4 - 1:
            raise ProtocolError(f"invalid light slot {slot}")
        buf[slot * 4 : slot * 4 + 4] = bytes((slot, r, g, b))
    buf[size - 2 : size] = b"\xaa\x55"
    return bytes(buf)


def screen_payload(frames: list[tuple[bytes, int]]) -> list[bytes]:
    """Header [count, delay per frame (ms / 2, at least 1), 0xff...] then the frames, in 4 KiB chunks."""
    if not 0 < len(frames) <= SCREEN_MAX_FRAMES:
        raise ProtocolError(f"1-{SCREEN_MAX_FRAMES} frames")
    header = bytearray(b"\xff" * SCREEN_HEADER)
    header[0] = len(frames)
    body = bytearray()
    for n, (pixels, duration_ms) in enumerate(frames):
        if len(pixels) != SCREEN_FRAME:
            raise ProtocolError(f"frame {n} is {len(pixels)} bytes, expected {SCREEN_FRAME}")
        header[1 + n] = max(1, min(0xFF, duration_ms // 2))
        body += pixels
    data = bytes(header) + bytes(body)
    count = -(-len(data) // SCREEN_CHUNK)
    data = data.ljust(count * SCREEN_CHUNK, b"\xff")
    return [data[i : i + SCREEN_CHUNK] for i in range(0, len(data), SCREEN_CHUNK)]


class ScreenPipe(Protocol):
    def write(self, data: bytes) -> int: ...
    def read(self, size: int, timeout_ms: int) -> bytes: ...


class Session:
    """Sends packets with the vendor driver's pacing and acknowledgement checks."""

    def __init__(self, link: FeatureLink | None, dry_run: bool = False,
                 log: Callable[[str], None] | None = None, delay: float = 0.01,
                 busy_polls: int = 150, busy_delay: float = 0.02, trace: bool = False) -> None:
        self.link = link
        self.trace = trace
        self.dry_run = dry_run
        self.log = log or (lambda msg: print(msg, file=sys.stderr))
        self.delay = delay
        self.busy_polls = busy_polls
        self.busy_delay = busy_delay

    def send(self, packet: bytes, ack: bool = True) -> None:
        if self.dry_run or self.link is None:
            self.log(f"[dry-run if={CONFIG_INTERFACE} feature] {packet.hex(' ')}")
            return
        if self.trace:
            self.log(f"> {packet.hex(' ')}")
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
        if packet[0] == 0x04:
            for _ in range(self.busy_polls):
                if len(reply) > 3 and reply[3] != 0xFF:
                    break
                time.sleep(self.busy_delay)
                reply = self.link.get_feature(0, PACKET)
        if self.trace:
            self.log(f"< {bytes(reply).hex(' ')}")
        if packet[0] != 0x04:
            return
        if len(reply) < 4 or reply[3] not in (0, 1):
            self.log(f"warning: no confirmation for {packet[:2].hex(' ')}: reply {bytes(reply[:8]).hex(' ')}")

    def set_lighting(self, settings: Lighting) -> None:
        self.send(command(START))
        self.send(command(MODE, byte8=1))
        self.send(lighting_data(settings), ack=False)
        self.send(command(SAVE))
        self.send(command(FINISH))

    def write_keymap(self, entries: dict[int, bytes], layer: int = KEYMAP) -> None:
        """Replace one layer's remaps (KEYMAP or FN_KEYMAP); slots not in *entries* return to default."""
        if layer not in (KEYMAP, FN_KEYMAP):
            raise ProtocolError(f"unknown keymap layer 0x{layer:02x}")
        payload = keymap_payload(entries)
        self.send(command(START))
        self.send(command(layer, byte8=KEYMAP_PACKETS))
        for offset in range(0, len(payload), PACKET):
            self.send(payload[offset : offset + PACKET], ack=False)
        self.send(command(SAVE))
        self.send(command(FINISH))

    def set_system(self, settings: System) -> None:
        self.send(command(START))
        self.send(command(SYSTEM, byte8=1))
        self.send(system_data(settings), ack=False)
        self.send(command(SAVE))  # the vendor driver sends no FINISH here

    def read_key_colors(self) -> dict[int, tuple[int, int, int]]:
        """Read the colour each LED shows right now, as the vendor driver's light-sync view does.

        04 f5 with byte 8 = 9, then nine 64-byte feature reads forming the slot table [slot, R, G, B],
        then 04 02. Decoded from the driver, not yet confirmed on hardware.
        """
        if self.dry_run or self.link is None:
            self.send(command(READ_LEDS, byte8=KEY_COLOR_PACKETS))
            return {}
        packet = command(READ_LEDS, byte8=KEY_COLOR_PACKETS)
        if self.trace:
            self.log(f"> {packet.hex(' ')}")
        self.link.set_feature(packet)
        time.sleep(0.01)
        table = bytearray()
        for _ in range(KEY_COLOR_PACKETS):
            reply = bytes(self.link.get_feature(0, PACKET))
            if self.trace:
                self.log(f"< {reply.hex(' ')}")
            table += reply.ljust(PACKET, b"\0")[:PACKET]
        self.send(command(SAVE))
        return {n: (table[n * 4 + 1], table[n * 4 + 2], table[n * 4 + 3])
                for n in range(1, len(table) // 4 - 1) if table[n * 4] == n}

    def write_macros(self, macros: list[list[tuple[str, int]]]) -> None:
        """Replace the macro table. Sequence from the vendor driver: 04 19, 04 15, data, 04 02."""
        packets, payload = macro_payload(macros)
        self.send(command(MACRO_BEGIN))
        self.send(command(MACROS, byte8=packets))
        time.sleep(0.03)
        for offset in range(0, len(payload), PACKET):
            self.send(payload[offset : offset + PACKET], ack=False)
        time.sleep(0.03)
        self.send(command(SAVE))

    def set_key_colors(self, colors: dict[int, tuple[int, int, int]], brightness: int = 5) -> None:
        """Store per-key colours and switch to the custom effect that displays them."""
        payload = key_colors_payload(colors)
        self.send(command(START))
        self.send(command(KEY_COLORS, byte8=KEY_COLOR_PACKETS))
        for offset in range(0, len(payload), PACKET):
            self.send(payload[offset : offset + PACKET], ack=False)
        self.send(command(SAVE))
        self.send(command(FINISH))
        self.set_lighting(Lighting(mode=CUSTOM_MODE, brightness=brightness, speed=MAX_LEVEL))

    def upload_screen(self, frames: list[tuple[bytes, int]], pipe: ScreenPipe | None, slot: int = 1,
                      progress: Callable[[int, int], None] | None = None) -> None:
        """Announce the upload on the configuration interface, stream it on the screen interface."""
        chunks = screen_payload(frames)
        self.send(command(START))
        header = bytearray(command(SCREEN, byte2=slot))
        header[8:10] = len(chunks).to_bytes(2, "little")
        self.send(bytes(header))
        for n, chunk in enumerate(chunks):
            if self.dry_run or pipe is None:
                if n == 0 or n == len(chunks) - 1:
                    self.log(f"[dry-run if={SCREEN_INTERFACE} output] chunk {n + 1}/{len(chunks)}: "
                             f"{chunk[:16].hex(' ')} ...")
                continue
            written = pipe.write(b"\x00" + chunk)
            if written < 0:
                raise ProtocolError(f"screen chunk {n + 1}/{len(chunks)} was not accepted")
            pipe.read(64, 300)  # the vendor driver waits for the keyboard's reply
            if progress:
                progress(n + 1, len(chunks))
        self.send(command(SAVE))

    def sync_time(self, when: datetime | None = None, save: bool = True) -> None:
        self.send(command(START))
        self.send(command(TIME, byte8=1))
        self.send(time_data(when or datetime.now()))
        if save:
            self.send(command(SAVE))
