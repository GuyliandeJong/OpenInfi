"""High-level keyboard operations: build packets, route them to the right interface."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import protocol, screen
from .capture import Report
from .profile import Profile
from .transport import DeviceError, Transport


class Keyboard:
    def __init__(self, profile: Profile, transport: Transport) -> None:
        self.profile = profile
        self.transport = transport

    @property
    def _size(self) -> int:
        return self.profile.packet_size

    def set_lighting(self, settings: protocol.Lighting) -> None:
        packets = protocol.lighting(settings, self._size)
        self.transport.send(packets, self.profile.lighting_interface)

    def set_key_colors(self, colors: dict[str, tuple[int, int, int]], default=(0, 0, 0)) -> None:
        """*colors* maps profile key names (or ``#index``) to RGB; others get *default*."""
        by_index = {key.index: default for key in self.profile.keys}
        for name, color in colors.items():
            by_index[self.profile.key(name).index] = color
        packets = protocol.key_colors(by_index, self.profile.rgb_slots, size=self._size)
        self.transport.send(packets, self.profile.lighting_interface, erase_after_first=True)

    def probe_index(self, index: int, color=(255, 255, 255)) -> None:
        """Light exactly one firmware index; used to map indices to physical keys."""
        packets = protocol.key_colors({index: color}, self.profile.rgb_slots, size=self._size)
        self.transport.send(packets, self.profile.lighting_interface, erase_after_first=True)

    def remap(self, key_name: str, hid_code: int) -> None:
        key = self.profile.key(key_name)
        self.transport.send(protocol.remap(key.index, hid_code, self._size), self.profile.lighting_interface)

    def sync_time(self, when: datetime | None = None) -> None:
        packets = protocol.set_time(when or datetime.now(), self._size)
        self.transport.send(packets, self.profile.lighting_interface)

    def upload_image(self, path: str | Path, width: int | None = None, height: int | None = None) -> None:
        width = width or self.profile.screen_width
        height = height or self.profile.screen_height
        if not width or not height:
            raise DeviceError(
                "screen size unknown: pass --size WxH or set screen.width/height in the profile "
                "('infi75 capture analyze' on a capture of an image upload reveals it)"
            )
        pixels = screen.encode_file(path, width, height, self.profile.screen_transpose)
        packets = protocol.screen_image(pixels, self._size)
        self.transport.send(packets, self.profile.screen_interface, erase_after_first=True)

    def replay(self, reports: list[Report], interface_override: int | None = None) -> int:
        """Send captured reports unchanged, grouped by interface and report type."""
        sent = 0
        group: list[bytes] = []
        current: tuple[int | None, str | None] = (None, None)
        for report in reports:
            target = (
                interface_override if interface_override is not None else report.interface,
                "output" if report.kind in ("output", "interrupt") else
                "feature" if report.kind == "feature" else None,
            )
            if group and target != current:
                sent += self.transport.send(group, current[0], report_type=current[1])
                group = []
            current = target
            group.append(_hidapi_buffer(report, self._size))
        if group:
            sent += self.transport.send(group, current[0], report_type=current[1])
        return sent


def _hidapi_buffer(report: Report, packet_size: int) -> bytes:
    """Captured payloads omit report ID 0; hidapi needs it as the first byte.

    Payloads with a non-zero report ID already start with that ID. Text
    reports are sent as written, zero-padded to the profile's packet size.
    """
    if report.kind == "text":
        return report.data.ljust(packet_size, b"\0")
    if report.report_id:
        return report.data
    return b"\x00" + report.data
