from datetime import datetime

import pytest

from infi75 import cli, hfd


class FakeLink:
    """Echoes every feature write back with status 1, like the INFI75 does."""

    def __init__(self, status=1):
        self.sent, self.status, self.last = [], status, bytes(64)

    def set_feature(self, data, report_id=0):
        self.sent.append(bytes(data))
        self.last = bytes(data)
        return len(data)

    def get_feature(self, report_id=0, length=64):
        reply = bytearray(self.last[:4].ljust(64, b"\0"))
        reply[3] = self.status
        return bytes(reply)


def test_lighting_transaction_matches_vendor_driver():
    link = FakeLink()
    settings = hfd.Lighting(mode=hfd.MODES["breath"], color=(10, 200, 30), rainbow=False,
                            brightness=5, speed=2, direction=hfd.DIRECTIONS["right"])
    hfd.Session(link, delay=0).set_lighting(settings)
    heads = [p[:2].hex() for p in link.sent]
    assert heads == ["0418", "0413", "070a", "0402", "04f0"]
    assert link.sent[1][8] == 1
    data = link.sent[2]
    assert data[:4] == bytes([0x07, 10, 200, 30])
    assert data[8:12] == bytes([0, 5, 2, 3])
    assert data[14:16] == b"\xaa\x55"
    assert all(len(p) == 64 for p in link.sent)


def test_time_packet_layout():
    data = hfd.time_data(datetime(2026, 10, 13, 9, 41, 7))
    assert data[:9] == bytes([0x00, 0x01, 0x5A, 26, 10, 13, 9, 41, 7])
    assert data[62:] == b"\xaa\x55"


class BusyThenDone(FakeLink):
    """SAVE answers 0xff (busy) a few times before 0, as seen on the INFI75."""

    def __init__(self, busy_reads):
        super().__init__(status=0xFF)
        self.busy_reads = busy_reads

    def get_feature(self, report_id=0, length=64):
        if self.busy_reads == 0:
            self.status = 0
        else:
            self.busy_reads -= 1
        return super().get_feature(report_id, length)


def test_busy_save_is_polled_not_failed():
    logs = []
    link = BusyThenDone(busy_reads=3)
    hfd.Session(link, delay=0, busy_delay=0, log=logs.append).send(hfd.command(hfd.SAVE))
    assert logs == [] and len(link.sent) == 1


def test_missing_confirmation_warns_without_raising():
    logs = []
    hfd.Session(FakeLink(status=0x7E), delay=0, log=logs.append).send(hfd.command(hfd.START))
    assert logs and "no confirmation for 04 18" in logs[0]


def test_trace_logs_packets_and_replies():
    logs = []
    hfd.Session(FakeLink(), delay=0, log=logs.append, trace=True).send(hfd.command(hfd.START))
    assert logs[0].startswith("> 04 18 00 00")
    assert logs[1].startswith("< 04 18 00 01")
    assert len(logs) == 2


def test_data_packet_echo_is_not_checked():
    logs = []
    link = FakeLink(status=0x1A)  # byte 3 of the time packet is the year
    hfd.Session(link, delay=0, log=logs.append).send(hfd.time_data(datetime(2026, 10, 13)))
    assert logs == []


def test_resolve_mode_accepts_names_and_numbers():
    assert hfd.resolve_mode("Spectrum") == 0x08
    assert hfd.resolve_mode("0x13") == 0x13
    with pytest.raises(hfd.ProtocolError):
        hfd.resolve_mode("nope")


def test_cli_dry_run_uses_hfd_by_default(capsys):
    code = cli.main(["--dry-run", "rgb", "mode", "spectrum", "--brightness", "5", "--rainbow"])
    err = capsys.readouterr().err
    assert code == 0
    lines = [l for l in err.splitlines() if l.startswith("[dry-run")]
    assert [l.split("] ")[1][:5] for l in lines] == ["04 18", "04 13", "08 ff", "04 02", "04 f0"]


def test_off_is_single_on_at_zero_brightness(capsys):
    assert cli.main(["--dry-run", "rgb", "mode", "off"]) == 0
    data = [l for l in capsys.readouterr().err.splitlines() if l.startswith("[dry-run")][2]
    packet = bytes.fromhex(data.split("] ")[1])
    assert packet[0] == 0x02 and packet[9] == 0


def test_key_entry_encodings():
    assert hfd.key_entry("esc") == bytes([0x02, 0x00, 0x29, 0x00])
    assert hfd.key_entry("ctrl+c") == bytes([0x02, 0x01, 0x06, 0x00])
    assert hfd.key_entry("lctrl") == bytes([0x02, 0x01, 0x00, 0x00])
    assert hfd.key_entry("shift+alt") == bytes([0x02, 0x02 | 0x04, 0x00, 0x00])
    assert hfd.key_entry("volup") == bytes([0x03, 0xE9, 0x00, 0x00])
    assert hfd.key_entry("default") == bytes(4)
    with pytest.raises(hfd.ProtocolError):
        hfd.key_entry("a+b")


def test_keymap_payload_layout():
    payload = hfd.keymap_payload({55: hfd.key_entry("lctrl")})
    assert len(payload) == 640
    assert payload[55 * 4 : 55 * 4 + 4] == bytes([0x02, 0x01, 0x00, 0x00])
    assert payload[574:576] == b"\xaa\x55"
    assert not any(payload[:55 * 4]) and not any(payload[576:])


def test_write_keymap_transaction():
    link = FakeLink()
    hfd.Session(link, delay=0).write_keymap({55: hfd.key_entry("esc")})
    heads = [p[:2].hex() for p in link.sent]
    assert heads[:2] == ["0418", "0411"] and link.sent[1][8] == 9
    assert len(link.sent) == 2 + 10 + 2 and heads[-2:] == ["0402", "04f0"]


def test_remap_cli_accumulates_and_resets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    class Link(FakeLink):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

    link = Link()
    monkeypatch.setattr("infi75.usbctl.UsbHid", lambda *a, **k: link)
    assert cli.main(["remap", "CAPS", "lctrl"]) == 0
    assert cli.main(["remap", "F12", "volup"]) == 0
    table = b"".join(p for p in link.sent[-12:-2])
    assert table[55 * 4 : 55 * 4 + 4] == bytes([0x02, 0x01, 0, 0])
    assert table[13 * 4 : 13 * 4 + 4] == bytes([0x03, 0xE9, 0, 0])
    assert cli.main(["remap", "--reset"]) == 0
    table = b"".join(p for p in link.sent[-12:-2])
    assert not any(table[:574])
    assert (tmp_path / "infi75" / "keymap.json").read_text().strip() == "{}"


def test_key_colors_transaction():
    link = FakeLink()
    hfd.Session(link, delay=0).set_key_colors({1: (255, 0, 0), 55: (0, 0, 255)})
    heads = [p[:2].hex() for p in link.sent]
    assert heads[:2] == ["0418", "0423"] and link.sent[1][8] == 9
    data = b"".join(link.sent[2:11])
    assert len(data) == 576
    assert data[4:8] == bytes([1, 255, 0, 0]) and data[220:224] == bytes([55, 0, 0, 255])
    assert data[574:576] == b"\xaa\x55"
    assert heads[11:13] == ["0402", "04f0"]
    assert heads[13:] == ["0418", "0413", "80ff", "0402", "04f0"]
    assert link.sent[15][9:11] == bytes([5, 5])


def test_cli_rgb_keys_fills_every_layout_slot(capsys):
    assert cli.main(["--dry-run", "rgb", "keys", "ESC=red", "--default", "0,0,10"]) == 0
    lines = [l.split("] ")[1] for l in capsys.readouterr().err.splitlines() if l.startswith("[dry-run")]
    data = bytes.fromhex("".join(lines[2:11]))
    assert data[4:8] == bytes([1, 255, 0, 0])  # ESC, slot 1
    assert data[55 * 4 : 55 * 4 + 4] == bytes([55, 0, 0, 10])  # CAPS, slot 55
    assert data[14 * 4 : 14 * 4 + 4] == bytes(4)  # slot 14 has no key


def test_screen_payload_layout():
    frame = bytes(range(256)) * (hfd.SCREEN_FRAME // 256) + bytes(hfd.SCREEN_FRAME % 256)
    chunks = hfd.screen_payload([(frame, 100)])
    assert all(len(c) == 4096 for c in chunks)
    assert len(chunks) == -(-(256 + hfd.SCREEN_FRAME) // 4096) == 16
    data = b"".join(chunks)
    assert data[0] == 1 and data[1] == 50 and set(data[2:256]) == {0xFF}
    assert data[256 : 256 + hfd.SCREEN_FRAME] == frame
    assert set(data[256 + hfd.SCREEN_FRAME :]) == {0xFF}


class FakePipe:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, size, timeout_ms):
        return b""


def test_upload_screen_sequence():
    link, pipe = FakeLink(), FakePipe()
    frame = bytes(hfd.SCREEN_FRAME)
    hfd.Session(link, delay=0).upload_screen([(frame, 40), (frame, 40)], pipe, slot=1)
    assert [p[:2].hex() for p in link.sent] == ["0418", "0472", "0402"]
    header = link.sent[1]
    chunks = -(-(256 + 2 * hfd.SCREEN_FRAME) // 4096)
    assert header[2] == 1 and int.from_bytes(header[8:10], "little") == chunks
    assert len(pipe.writes) == chunks and all(len(w) == 4097 and w[0] == 0 for w in pipe.writes)
    assert pipe.writes[0][1:4] == bytes([2, 20, 20])


def test_frames_from_file_little_endian_portrait(tmp_path):
    from PIL import Image

    from infi75 import screen

    path = tmp_path / "red.png"
    Image.new("RGB", (240, 135), (255, 0, 0)).save(path)
    (pixels, duration), = screen.frames_from_file(path, 135, 240, 141, fit="stretch")
    assert len(pixels) == hfd.SCREEN_FRAME and pixels[:2] == b"\x00\xf8"


def test_board_saves_and_reloads_key_colours(tmp_path, monkeypatch):
    from infi75 import board as board_mod
    from infi75 import profile as profiles

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    class Link(FakeLink):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

    monkeypatch.setattr("infi75.usbctl.UsbHid", lambda *a, **k: Link())
    b = board_mod.InfiBoard(profiles.load())
    b.set_key_colors({"esc": (1, 2, 3)}, default=(0, 0, 9))
    assert b.saved_colors() == ({"ESC": (1, 2, 3)}, (0, 0, 9))
