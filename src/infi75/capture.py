"""Read USB captures of the official software and turn them into HID reports.

This is the tool for learning the INFI75's real protocol: record the
vendor software with Wireshark (USBPcap on Windows, usbmon on Linux) while
changing one setting, then inspect, diff and replay the reports here.

Supported inputs:
  * pcap / pcapng with link type USBPcap (249) or Linux usbmon (189, 220)
  * text: one hex-encoded report per line; ``# interface N`` switches the
    interface for the lines that follow; other ``#`` lines are comments
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

LINKTYPE_USBPCAP = 249
LINKTYPE_USB_LINUX = 189
LINKTYPE_USB_LINUX_MMAPPED = 220

SET_REPORT_REQUEST_TYPE = 0x21
SET_REPORT = 0x09
REPORT_TYPES = {1: "input", 2: "output", 3: "feature"}


class CaptureError(ValueError):
    pass


@dataclass(frozen=True)
class Report:
    """One HID report, host-to-device unless ``kind == "input"``."""

    data: bytes
    interface: int | None = None  # None when only the endpoint is known
    kind: str = "feature"  # feature | output | interrupt (host to device) | input (device to host)
    report_id: int | None = None
    device: int | None = None
    timestamp: float = 0.0


# ---------------------------------------------------------------- containers


def _pcap_records(blob: bytes):
    """Yield (linktype, timestamp, frame) from classic pcap or pcapng."""
    if len(blob) < 24:
        raise CaptureError("file too short to be a capture")
    magic = blob[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = "<" if magic[0] in (0xD4, 0x4D) else ">"
        nano = magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")
        linktype = struct.unpack_from(endian + "I", blob, 20)[0] & 0xFFFF
        offset = 24
        while offset + 16 <= len(blob):
            sec, frac, incl, _ = struct.unpack_from(endian + "IIII", blob, offset)
            offset += 16
            yield linktype, sec + frac / (1e9 if nano else 1e6), blob[offset : offset + incl]
            offset += incl
        return
    if magic == b"\x0a\x0d\x0d\x0a":
        yield from _pcapng_records(blob)
        return
    raise CaptureError("not a pcap or pcapng file")


def _pcapng_records(blob: bytes):
    endian = "<"
    linktypes: list[int] = []
    offset = 0
    while offset + 12 <= len(blob):
        if blob[offset : offset + 4] == b"\x0a\x0d\x0d\x0a":
            bom = blob[offset + 8 : offset + 12]
            endian = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"
            linktypes = []
        block_type, length = struct.unpack_from(endian + "II", blob, offset)
        if length < 12 or offset + length > len(blob):
            raise CaptureError(f"corrupt pcapng block at offset {offset}")
        body = blob[offset + 8 : offset + length - 4]
        if block_type == 1:  # interface description
            linktypes.append(struct.unpack_from(endian + "H", body, 0)[0])
        elif block_type == 6:  # enhanced packet
            iface, high, low, cap, _ = struct.unpack_from(endian + "IIIII", body, 0)
            yield linktypes[iface], ((high << 32) | low) / 1e6, body[20 : 20 + cap]
        elif block_type == 3 and linktypes:  # simple packet
            yield linktypes[0], 0.0, body[4:]
        offset += length


# ------------------------------------------------------------- link layers


def _setup_to_report(setup: bytes, data: bytes, device: int, ts: float) -> Report | None:
    request_type, request, value, index, _ = struct.unpack("<BBHHH", setup)
    if request_type != SET_REPORT_REQUEST_TYPE or request != SET_REPORT or not data:
        return None
    return Report(
        data=bytes(data),
        interface=index,
        kind=REPORT_TYPES.get(value >> 8, f"type{value >> 8}"),
        report_id=value & 0xFF,
        device=device,
        timestamp=ts,
    )


def _usbpcap(frames):
    pending: dict[int, tuple[bytes, int]] = {}
    for ts, frame in frames:
        if len(frame) < 27:
            continue
        hlen, irp, _status, _func, info, _bus, device, endpoint, transfer, dlen = struct.unpack_from(
            "<HQIHBHHBBI", frame, 0
        )
        payload = frame[hlen : hlen + dlen]
        to_device = not info & 0x01
        if transfer == 2 and hlen >= 28:  # control
            stage = frame[27]
            if stage == 0 and to_device and len(payload) >= 8:
                setup, rest = payload[:8], payload[8:]
                if rest:
                    report = _setup_to_report(setup, rest, device, ts)
                    if report:
                        yield report
                else:
                    pending[irp] = (setup, device)
            elif stage == 1 and to_device and irp in pending:
                setup, dev = pending.pop(irp)
                report = _setup_to_report(setup, payload, dev, ts)
                if report:
                    yield report
        elif transfer == 1 and to_device and not endpoint & 0x80 and payload:
            yield Report(data=bytes(payload), kind="interrupt", device=device, timestamp=ts)
        elif transfer == 1 and not to_device and endpoint & 0x80 and payload:
            yield Report(data=bytes(payload), kind="input", device=device, timestamp=ts)


def _usbmon(frames, header_len: int):
    for ts, frame in frames:
        if len(frame) < header_len:
            continue
        _id, ev, xfer, ep, dev, _bus, flag_setup, _flag_data = struct.unpack_from("<QcBBBHbb", frame, 0)
        data = frame[header_len:]
        if ev == b"C" and ep & 0x80 and xfer == 1 and data:
            yield Report(data=bytes(data), kind="input", device=dev, timestamp=ts)
            continue
        if ev != b"S" or ep & 0x80:
            continue
        if xfer == 2 and flag_setup == 0:
            report = _setup_to_report(frame[40:48], data, dev, ts)
            if report:
                yield report
        elif xfer == 1 and data:
            yield Report(data=bytes(data), kind="interrupt", device=dev, timestamp=ts)


def _from_pcap(blob: bytes) -> list[Report]:
    by_link: dict[int, list] = {}
    for linktype, ts, frame in _pcap_records(blob):
        by_link.setdefault(linktype, []).append((ts, frame))
    reports: list[Report] = []
    for linktype, frames in by_link.items():
        if linktype == LINKTYPE_USBPCAP:
            reports += _usbpcap(frames)
        elif linktype == LINKTYPE_USB_LINUX_MMAPPED:
            reports += _usbmon(frames, 64)
        elif linktype == LINKTYPE_USB_LINUX:
            reports += _usbmon(frames, 48)
        else:
            raise CaptureError(f"unsupported link type {linktype}; capture USB with USBPcap or usbmon")
    return sorted(reports, key=lambda r: r.timestamp)


def _from_text(text: str) -> list[Report]:
    reports = []
    interface: int | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            words = line[1:].split()
            if len(words) == 2 and words[0].lower() == "interface":
                interface = None if words[1].lower() == "any" else int(words[1], 0)
            continue
        hexdigits = line.replace(" ", "").replace(":", "").replace(",", "")
        try:
            data = bytes.fromhex(hexdigits)
        except ValueError:
            raise CaptureError(f"line {lineno}: not hex: {raw!r}") from None
        reports.append(Report(data=data, interface=interface, kind="text"))
    return reports


def outgoing(reports: list[Report]) -> list[Report]:
    """Only host-to-device reports (what replay and diff operate on)."""
    return [r for r in reports if r.kind != "input"]


def load(path: str | Path) -> list[Report]:
    blob = Path(path).read_bytes()
    if blob[:4] in (
        b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d", b"\x0a\x0d\x0d\x0a",
    ):
        return _from_pcap(blob)
    try:
        return _from_text(blob.decode("utf-8"))
    except UnicodeDecodeError:
        raise CaptureError(f"{path}: neither a capture nor a text report list") from None


def to_text(reports: list[Report]) -> str:
    """Serialise reports in the text format accepted by :func:`load`."""
    lines = []
    interface: object = object()
    for report in reports:
        if report.interface != interface:
            interface = report.interface
            lines.append(f"# interface {'any' if interface is None else interface}")
        lines.append(report.data.hex(" "))
    return "\n".join(lines) + "\n"


def diff(a: list[Report], b: list[Report]) -> list[tuple[int, list[tuple[int, int, int]]]]:
    """Pairwise byte differences: [(packet_no, [(offset, a_byte, b_byte), ...]), ...].

    Packets are compared position by position; a length mismatch shows as
    differences against 0x00 (missing bytes) beyond the shorter packet.
    """
    result = []
    for n, (ra, rb) in enumerate(zip(a, b)):
        size = max(len(ra.data), len(rb.data))
        da, db = ra.data.ljust(size, b"\0"), rb.data.ljust(size, b"\0")
        changes = [(i, da[i], db[i]) for i in range(size) if da[i] != db[i]]
        if changes:
            result.append((n, changes))
    return result
