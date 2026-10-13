import pytest

from infi75 import probe
from infi75 import profile as profiles
from infi75.device import Keyboard
from infi75.transport import DeviceError, Transport, udev_rule

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


def test_unconfirmed_protocol_blocks_writes():
    prof = profiles.load()
    assert prof.protocol == "unconfirmed"
    keyboard = Keyboard(prof, Transport(prof, dry_run=False))
    with pytest.raises(DeviceError, match="infi75 probe"):
        keyboard.sync_time()


def test_udev_rule_is_scoped_to_product():
    rule = udev_rule(0x05AC, [0x024F])
    assert 'ATTRS{idVendor}=="05ac", ATTRS{idProduct}=="024f"' in rule
    assert rule.count("SUBSYSTEM") == 1
