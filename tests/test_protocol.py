from datetime import datetime

import pytest

from infi75 import protocol

# Expected bytes produced by the epomaker-controller RT100 implementation.


def test_lighting_matches_reference():
    settings = protocol.Lighting(protocol.Mode.BREATHING, (10, 200, 30), 4, 4, False, protocol.Direction.LEFT)
    (packet,) = protocol.lighting(settings)
    assert len(packet) == 64
    assert packet.rstrip(b"\0").hex() == "07020404170ac81ee7"


def test_remap_matches_reference():
    (packet,) = protocol.remap(41, 0x29)
    assert packet.rstrip(b"\0").hex() == "13002900000000c3000029"


def test_time_matches_reference():
    (packet,) = protocol.set_time(datetime(2026, 10, 12, 13, 45, 7))
    assert packet.rstrip(b"\0").hex() == "28000000000000d707ea0a0c0d2d07"


def test_key_colors_layout():
    packets = protocol.key_colors({0: (1, 2, 3), 20: (4, 5, 6)}, slots=130)
    assert len(packets) == 8 and all(len(p) == 64 for p in packets)
    assert packets[0].rstrip(b"\0").hex() == "18000000000000e7"
    first = packets[1]
    assert first[:7] == bytes([0x19, 0, 0, 1, 0, 0, 0])
    assert first[7] == protocol.checksum(first[:7])
    assert first[8:11] == bytes([1, 2, 3])
    # index 20 -> byte 60 of the colour buffer -> packet 2, payload offset 4
    assert packets[2][8 + 4 : 8 + 7] == bytes([4, 5, 6])


def test_key_colors_rejects_out_of_range_index():
    with pytest.raises(ValueError):
        protocol.key_colors({130: (1, 1, 1)}, slots=130)


def test_screen_image_framing():
    pixels = bytes(range(256)) * 3  # 768 bytes -> 14 packets (13 x 56 + 40)
    packets = protocol.screen_image(pixels)
    assert packets[0][:7] == bytes([0xA5, 0, 1, 0]) + (768).to_bytes(3, "little")
    assert packets[0][7] == protocol.checksum(packets[0][:7])
    assert len(packets) == 1 + 14
    last = packets[-1]
    assert int.from_bytes(last[4:6], "little") == 13 and last[6] == 768 - 13 * 56
    assert b"".join(p[8 : 8 + p[6]] for p in packets[1:]) == pixels


def test_rt100_image_start_packet():
    (start, *_) = protocol.screen_image(bytes(162 * 173 * 2))
    assert start.rstrip(b"\0").hex() == "a5000100f4da008b0000a2ad"


@pytest.mark.parametrize("bad", [dict(speed=6), dict(brightness=5), dict(color=(256, 0, 0))])
def test_lighting_validation(bad):
    with pytest.raises(ValueError):
        protocol.lighting(protocol.Lighting(**bad))


def test_describe_roundtrip():
    (packet,) = protocol.remap(41, 0x29)
    assert protocol.describe(packet) == "remap key index=41 -> HID 0x29"
    (start, *_) = protocol.screen_image(bytes(240 * 135 * 2))
    assert "32400 RGB565 pixels" in protocol.describe(start)


def test_describe_online_frames():
    request = bytes.fromhex("aa1038000000010000")
    assert protocol.describe(request) == "online request GET_DEVICE_INFO len=56 addr=0 last=1"
    assert protocol.describe(bytes.fromhex("5523100000000000")).startswith("online reply SET_LED_EFFECT")
