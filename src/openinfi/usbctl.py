"""HID requests over the USB control pipe, via libusb (pyusb).

The INFI75-1.2 firmware exposes its fourth interface as HID with only an
OUT endpoint. The kernel HID driver needs an IN endpoint, so it leaves the
interface unbound and no hidraw node exists. Feature reports travel over
endpoint 0, so they can still be exchanged as raw class requests.
"""

from __future__ import annotations

GET_DESCRIPTOR = 0x06
HID_REPORT_DESCRIPTOR = 0x22
GET_REPORT = 0x01
SET_REPORT = 0x09
FEATURE = 3


class UsbError(RuntimeError):
    pass


def _usb():
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise UsbError("pyusb is not installed: pip install pyusb") from exc
    return usb


class UsbHid:
    """One HID interface addressed through control transfers."""

    def __init__(self, vendor_id: int, product_id: int, interface: int, timeout_ms: int = 1000) -> None:
        usb = _usb()
        self._usb = usb
        self.device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if self.device is None:
            raise UsbError(f"USB device {vendor_id:04x}:{product_id:04x} not found")
        self.interface = interface
        self.timeout = timeout_ms
        try:
            if self.device.is_kernel_driver_active(interface):
                raise UsbError(f"interface {interface} is bound to a kernel driver; refusing to detach it")
        except NotImplementedError:
            pass
        except usb.core.USBError as exc:
            raise UsbError(f"cannot access the device: {exc} (install the udev rule: 'openinfi udev')") from exc

    def __enter__(self) -> "UsbHid":
        try:
            self._usb.util.claim_interface(self.device, self.interface)
        except self._usb.core.USBError as exc:
            raise UsbError(f"cannot claim interface {self.interface}: {exc}") from exc
        return self

    def __exit__(self, *exc) -> None:
        self._usb.util.release_interface(self.device, self.interface)
        self._usb.util.dispose_resources(self.device)

    def report_descriptor(self, length: int = 1024) -> bytes:
        return bytes(
            self.device.ctrl_transfer(
                0x81, GET_DESCRIPTOR, HID_REPORT_DESCRIPTOR << 8, self.interface, length, self.timeout
            )
        )

    def get_feature(self, report_id: int = 0, length: int = 64) -> bytes:
        return bytes(
            self.device.ctrl_transfer(
                0xA1, GET_REPORT, (FEATURE << 8) | report_id, self.interface, length, self.timeout
            )
        )

    def set_feature(self, data: bytes, report_id: int = 0) -> int:
        return self.device.ctrl_transfer(
            0x21, SET_REPORT, (FEATURE << 8) | report_id, self.interface, data, self.timeout
        )
