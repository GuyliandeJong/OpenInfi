"""HID device discovery via hidapi, and the udev rule for non-root access."""

from __future__ import annotations

import sys
from dataclasses import dataclass


class DeviceError(RuntimeError):
    pass


def _hid():
    # On Linux the "hidapi" wheel's `hid` module uses libusb, which detaches
    # the kernel driver from the opened interface; its `hidraw` module talks
    # to /dev/hidraw* instead and leaves the keyboard untouched.
    if sys.platform.startswith("linux"):
        try:
            import hidraw

            return hidraw
        except ImportError:
            pass
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


def udev_rule(vendor_id: int, product_ids: list[int] | None = None) -> str:
    lines = ["# infi75: allow the logged-in user to access the keyboard's HID interfaces"]
    for pid in product_ids or [None]:
        match = f'ATTRS{{idVendor}}=="{vendor_id:04x}"'
        if pid is not None:
            match += f', ATTRS{{idProduct}}=="{pid:04x}"'
        lines.append(f'SUBSYSTEM=="hidraw", {match}, MODE="0660", TAG+="uaccess"')
        # libusb access for interfaces the HID driver leaves unbound
        lines.append(f'SUBSYSTEM=="usb", ENV{{DEVTYPE}}=="usb_device", {match.replace("ATTRS", "ATTR")}, '
                     'MODE="0660", TAG+="uaccess"')
        if pid is not None:
            # start the user's clock sync (infi75 clock install) when the keyboard is plugged in;
            # 05ac is Apple's vendor ID, so also match the product name
            lines.append(f'SUBSYSTEM=="usb", ENV{{DEVTYPE}}=="usb_device", '
                         f'{match.replace("ATTRS", "ATTR")}, ATTR{{product}}=="INFI75*", '
                         'TAG+="systemd", ENV{SYSTEMD_USER_WANTS}+="infi75-clock.service"')
            # Bluetooth HID (bus 0005) has no USB attributes; match the HID device name
            lines.append(f'SUBSYSTEM=="hidraw", KERNELS=="0005:{vendor_id:04X}:{pid:04X}.*", '
                         'MODE="0660", TAG+="uaccess"')
    return "\n".join(lines) + "\n"
