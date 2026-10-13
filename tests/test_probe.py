from infi75 import probe
from infi75.transport import udev_rule

# Vendor collection 0xFF68/0x61: 64-byte input, 4096-byte output, no report IDs.
LCD_DESCRIPTOR = bytes.fromhex(
    "06 68 ff 09 61 a1 01"  # usage page 0xff68, usage 0x61, collection(application)
    " 15 00 26 ff 00 75 08"  # logical 0..255, report size 8
    " 95 40 09 62 81 02"  # report count 64, input
    " 96 00 10 09 63 91 02"  # report count 4096, output
    " c0"
)
# Report ID 4 feature collection on 0xFFFF plus a consumer collection with ID 3.
CONFIG_DESCRIPTOR = bytes.fromhex(
    "06 ff ff 09 01 a1 01 85 04 75 08 95 3f 09 02 b1 02 c0"
    "05 0c 09 01 a1 01 85 03 75 10 95 01 09 e9 81 00 c0"
)


def test_parse_report_descriptor_sizes():
    (lcd,) = probe.parse_report_descriptor(LCD_DESCRIPTOR)
    assert (lcd.usage_page, lcd.usage) == (0xFF68, 0x61)
    assert lcd.reports == {("input", 0): 64, ("output", 0): 4096}
    config, consumer = probe.parse_report_descriptor(CONFIG_DESCRIPTOR)
    assert config.usage_page == 0xFFFF and config.reports == {("feature", 4): 63}
    assert consumer.usage_page == 0x000C and consumer.reports == {("input", 3): 2}


def test_online_frame_layout():
    frame = probe.online_frame(probe.GET_DEVICE_INFO, 48)
    assert len(frame) == 64
    assert frame[:8] == bytes([0xAA, 0x10, 0x30, 0, 0, 0, 1, 0])
    assert not any(frame[8:])


def test_parse_device_info():
    payload = bytearray(48)
    payload[4:8] = bytes([0xAC, 0x05, 0x4F, 0x02])
    payload[8], payload[9] = 0x07, 0x01  # firmware 1.07
    payload[17] = 80
    info = probe.parse_device_info(bytes(payload))
    assert info["firmware"] == "1.07" and info["vid"] == "0x05ac" and info["pid"] == "0x024f"
    assert info["battery"] == 80


def test_udev_rule_is_scoped_to_product():
    rule = udev_rule(0x05AC, [0x024F])
    assert 'ATTRS{idVendor}=="05ac", ATTRS{idProduct}=="024f"' in rule
    assert rule.count('SUBSYSTEM=="hidraw"') == 2  # USB and Bluetooth
    assert 'SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="05ac", ATTR{idProduct}=="024f"' in rule
    assert 'KERNELS=="0005:05AC:024F.*"' in rule


class _FakeHid:
    def __init__(self, fail_reads=False):
        self.sent, self.fail_reads = [], fail_reads

    def device(self):
        return self

    def open_path(self, path):
        pass

    def close(self):
        pass

    def send_feature_report(self, data):
        self.sent.append(bytes(data))
        return len(data)

    def get_feature_report(self, rid, size):
        if self.fail_reads:
            raise OSError("read error")
        return [0, 0x04, 0x18] + [0] * 62


def test_handshake_sends_only_start_and_end():
    fake = _FakeHid()
    assert probe.handshake(fake, b"/dev/x", lambda m: None) is True
    assert [p[:3] for p in fake.sent] == [b"\x00\x04\x18", b"\x00\x04\x02"]
    assert all(len(p) == 65 and not any(p[3:]) for p in fake.sent)
    assert probe.handshake(_FakeHid(fail_reads=True), b"/dev/x", lambda m: None) is False


class _FakeUsbDevice:
    def __init__(self):
        self.calls = []

    def is_kernel_driver_active(self, interface):
        return False

    def ctrl_transfer(self, request_type, request, value, index, data_or_length, timeout):
        self.calls.append((request_type, request, value, index))
        if isinstance(data_or_length, int):
            return bytes([0x06, 0x13, 0xFF]) if request == 0x06 else bytes(data_or_length)
        return len(data_or_length)


def test_usb_control_requests(monkeypatch):
    import types

    from infi75 import usbctl

    fake = _FakeUsbDevice()
    usb_mod = types.SimpleNamespace(
        core=types.SimpleNamespace(find=lambda **kw: fake, USBError=OSError),
        util=types.SimpleNamespace(
            claim_interface=lambda d, i: None, release_interface=lambda d, i: None, dispose_resources=lambda d: None
        ),
    )
    monkeypatch.setattr(usbctl, "_usb", lambda: usb_mod)
    with usbctl.UsbHid(0x05AC, 0x024F, 3) as dev:
        assert dev.report_descriptor()[:3] == b"\x06\x13\xff"
        dev.get_feature()
        dev.set_feature(bytes([0x04, 0x18]) + bytes(62))
    assert fake.calls == [(0x81, 0x06, 0x2200, 3), (0xA1, 0x01, 0x0300, 3), (0x21, 0x09, 0x0300, 3)]
