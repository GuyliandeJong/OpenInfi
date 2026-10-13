"""Read-only identification of the keyboard's configuration protocol.

Two protocol families are known to run on SONiX-based boards that report
USB ID 05ac:024f (the INFI75 among them):

* "online": the AJAZZ/HFD web-driver protocol. Output reports with report
  ID 0, frames starting with 0xAA; the keyboard answers with input reports
  starting with 0x55. Documented by https://github.com/wsclx/ak820pro-modder
  (docs/PROTOCOL.md).
* "legacy": 64-byte feature reports starting with 0x04, as used by OpenRGB's
  Valkyrie VK99 controller and https://github.com/snailb1007/MonKey.

Probing sends only GET_DEVICE_INFO (a read command) and reads feature
reports. It never writes settings.
"""

from __future__ import annotations

import glob
import os
import re
import time
from dataclasses import dataclass, field

GET_DEVICE_INFO = 0x10


# ---------------------------------------------------------------- descriptors


@dataclass
class Collection:
    usage_page: int
    usage: int
    # (kind, report_id) -> size in bytes, kind in input/output/feature
    reports: dict[tuple[str, int], int] = field(default_factory=dict)


def parse_report_descriptor(desc: bytes) -> list[Collection]:
    """Top-level collections with their report sizes (excluding the ID byte)."""
    collections: list[Collection] = []
    usage_page = report_size = report_count = report_id = 0
    usage = 0
    stack: list[tuple[int, int, int, int]] = []
    depth = 0
    bits: dict[tuple[str, int], int] = {}
    i = 0
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:  # long item
            i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        kind, tag = (prefix >> 2) & 0x03, prefix >> 4
        data = int.from_bytes(desc[i + 1 : i + 1 + size], "little")
        i += 1 + size
        if kind == 1:  # global
            if tag == 0:
                usage_page = data
            elif tag == 7:
                report_size = data
            elif tag == 8:
                report_id = data
            elif tag == 9:
                report_count = data
            elif tag == 10:
                stack.append((usage_page, report_size, report_count, report_id))
            elif tag == 11 and stack:
                usage_page, report_size, report_count, report_id = stack.pop()
        elif kind == 2 and tag == 0:  # local usage
            usage = data
        elif kind == 0:  # main
            if tag == 10:  # collection
                if depth == 0:
                    collections.append(Collection(usage_page, usage & 0xFFFF))
                    bits = collections[-1].reports
                depth += 1
            elif tag == 12:
                depth = max(0, depth - 1)
            elif tag in (8, 9, 11) and collections:
                name = {8: "input", 9: "output", 11: "feature"}[tag]
                bits[(name, report_id)] = bits.get((name, report_id), 0) + report_size * report_count
            usage = 0
    for collection in collections:
        collection.reports = {k: (v + 7) // 8 for k, v in collection.reports.items()}
    return collections


@dataclass
class HidrawNode:
    path: str  # /dev/hidrawN
    vendor_id: int
    product_id: int
    interface: int
    name: str
    collections: list[Collection]


def linux_nodes(vendor_id: int, product_id: int) -> list[HidrawNode]:
    nodes = []
    for sys_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sys_dir, "device", "uevent"), encoding="utf-8") as handle:
                uevent = dict(line.strip().split("=", 1) for line in handle if "=" in line)
            with open(os.path.join(sys_dir, "device", "report_descriptor"), "rb") as handle:
                descriptor = handle.read()
        except OSError:
            continue
        match = re.match(r"[0-9A-Fa-f]+:([0-9A-Fa-f]+):([0-9A-Fa-f]+)", uevent.get("HID_ID", ""))
        if not match:
            continue
        vid, pid = int(match.group(1), 16), int(match.group(2), 16)
        if (vid, pid) != (vendor_id, product_id):
            continue
        real = os.path.realpath(os.path.join(sys_dir, "device"))
        iface = re.search(r":\d+\.(\d+)/[^/]+$", real)
        nodes.append(
            HidrawNode(
                path="/dev/" + os.path.basename(sys_dir),
                vendor_id=vid,
                product_id=pid,
                interface=int(iface.group(1)) if iface else -1,
                name=uevent.get("HID_NAME", ""),
                collections=parse_report_descriptor(descriptor),
            )
        )
    return nodes


# -------------------------------------------------------------------- queries


def online_frame(cmd: int, length: int, addr: int = 0, last: bool = True, size: int = 64) -> bytes:
    frame = bytearray(size)
    frame[0], frame[1], frame[2] = 0xAA, cmd, length
    frame[3], frame[4] = addr & 0xFF, (addr >> 8) & 0xFF
    frame[6] = 1 if last else 0
    return bytes(frame)


def parse_device_info(payload: bytes) -> dict[str, object]:
    g = lambda i: payload[i] if i < len(payload) else 0  # noqa: E731
    w = lambda i: g(i) | (g(i + 1) << 8)  # noqa: E731
    version = ((g(8) & 0x0F) + ((g(8) & 0xF0) >> 4) * 10 + g(9) * 100) / 100
    return {
        "firmware": f"{version:.2f}",
        "vid": f"0x{w(4):04x}",
        "pid": f"0x{w(6):04x}",
        "work_mode": g(16),
        "battery": g(17),
        "profile": g(19),
        "tft_max_frames": w(22),
        "tft_direction": g(28),
        "lighting_version": g(31),
    }


def query_online(hid_module, path: bytes, out_size: int, log) -> bool:
    """Send GET_DEVICE_INFO as an output report; True if the board answered."""
    device = hid_module.device()
    device.open_path(path)
    try:
        frame = online_frame(GET_DEVICE_INFO, 48, size=out_size)
        log(f"  TX output: {frame[:8].hex(' ')} ... ({out_size} bytes)")
        if device.write(b"\x00" + frame) < 0:
            log("  write failed")
            return False
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            data = bytes(device.read(4200, 200))
            if not data:
                continue
            log(f"  RX input:  {data[:32].hex(' ')}{' ...' if len(data) > 32 else ''}")
            if data[0] == 0x55 and data[1] == GET_DEVICE_INFO:
                log(f"  device info: {parse_device_info(data[8:])}")
                return True
        log("  no 0x55 reply")
        return False
    finally:
        device.close()


def read_features(hid_module, path: bytes, report_ids: list[int], log) -> None:
    device = hid_module.device()
    device.open_path(path)
    try:
        for rid in report_ids:
            try:
                data = bytes(device.get_feature_report(rid, 65))
                log(f"  GET_FEATURE id={rid}: {data[:24].hex(' ')}{' ...' if len(data) > 24 else ''}")
            except (OSError, ValueError) as exc:
                log(f"  GET_FEATURE id={rid}: {exc}")
    finally:
        device.close()
