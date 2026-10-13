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
