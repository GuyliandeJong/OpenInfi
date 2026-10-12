"""HID transport: device discovery and report I/O via hidapi."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .profile import Profile


class DeviceError(RuntimeError):
    pass


def _hid():
    try:
        import hid  # provided by the "hidapi" package
    except ImportError as exc:
        raise DeviceError("hidapi is not installed: pip install hidapi") from exc
    return hid


@dataclass(frozen=True)
class HidInterface:
    vendor_id: int
    product_id: int
    interface: int
    usage_page: int
    usage: int
    product: str
    manufacturer: str
    path: bytes

    def __str__(self) -> str:
        return (
            f"{self.vendor_id:04x}:{self.product_id:04x} if={self.interface} "
            f"usage_page=0x{self.usage_page:04x} usage=0x{self.usage:02x} "
            f"{self.manufacturer!r} {self.product!r}"
        )


def enumerate_interfaces(vendor_id: int = 0, product_id: int = 0) -> list[HidInterface]:
    hid = _hid()
    found = []
    for info in hid.enumerate(vendor_id, product_id):
        found.append(
            HidInterface(
                vendor_id=info["vendor_id"],
                product_id=info["product_id"],
                interface=info.get("interface_number", -1),
                usage_page=info.get("usage_page", 0),
                usage=info.get("usage", 0),
                product=info.get("product_string") or "",
                manufacturer=info.get("manufacturer_string") or "",
                path=info["path"],
            )
        )
    return sorted(found, key=lambda i: (i.vendor_id, i.product_id, i.interface, i.usage_page))


class Transport:
    """Sends reports to one interface of the keyboard, or prints them in dry-run mode."""

    def __init__(
        self,
        profile: Profile,
        product_id: int | None = None,
        dry_run: bool = False,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.profile = profile
        self.product_id = product_id
        self.dry_run = dry_run
        self.log = log or (lambda msg: print(msg, file=sys.stderr))

    def find(self, interface: int | None) -> HidInterface:
        if self.product_id is not None:
            allowed = {self.product_id}
        else:
            allowed = set(self.profile.product_ids)
        candidates = [
            i
            for i in enumerate_interfaces(self.profile.vendor_id)
            if not allowed or i.product_id in allowed
        ]
        if not candidates:
            raise DeviceError(
                f"no HID device with vendor id 0x{self.profile.vendor_id:04x} found; "
                "run 'infi75 list --all' to see connected devices and pass --vid/--pid"
            )
        pids = sorted({c.product_id for c in candidates})
        if len(pids) > 1:
            raise DeviceError(
                "several matching devices: "
                + ", ".join(f"{p:04x}" for p in pids)
                + "; choose one with --pid"
            )
        if interface is None:
            vendor = [c for c in candidates if c.usage_page >= 0xFF00]
            return (vendor or candidates)[0]
        for candidate in candidates:
            if candidate.interface == interface:
                return candidate
        raise DeviceError(
            f"interface {interface} not present; available: "
            + ", ".join(str(c.interface) for c in candidates)
        )

    def send(
        self,
        packets: Iterable[bytes],
        interface: int | None,
        erase_after_first: bool = False,
        report_type: str | None = None,
    ) -> int:
        """Send *packets* in order with the profile's pacing. Returns the packet count.

        The first byte of each packet is the HID report ID as hidapi expects;
        a leading 0x00 is stripped by the OS for devices without report IDs.
        """
        packets = list(packets)
        report_type = report_type or self.profile.report_type
        pace = self.profile.pacing_ms / 1000
        erase = self.profile.erase_delay_ms / 1000
        if self.dry_run:
            for n, packet in enumerate(packets):
                self.log(f"[dry-run if={interface} {report_type}] {n:4d}: {packet.hex(' ')}")
            return len(packets)

        target = self.find(interface)
        hid = _hid()
        device = hid.device()
        try:
            device.open_path(target.path)
        except OSError as exc:
            raise DeviceError(
                f"cannot open {target}: {exc}. On Linux install the udev rule "
                "('infi75 udev') or run as root."
            ) from exc
        try:
            for n, packet in enumerate(packets):
                if report_type == "output":
                    written = device.write(packet)
                else:
                    written = device.send_feature_report(packet)
                if written < 0:
                    raise DeviceError(f"write failed on packet {n}: {device.error()}")
                time.sleep(erase if (n == 0 and erase_after_first) else pace)
        finally:
            device.close()
        return len(packets)


def udev_rule(vendor_id: int) -> str:
    return (
        "# infi75: allow non-root access to the keyboard's HID interfaces\n"
        f'SUBSYSTEM=="hidraw", ATTRS{{idVendor}}=="{vendor_id:04x}", MODE="0660", TAG+="uaccess"\n'
        f'SUBSYSTEM=="usb", ATTRS{{idVendor}}=="{vendor_id:04x}", MODE="0660", TAG+="uaccess"\n'
    )
