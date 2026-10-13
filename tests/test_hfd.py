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


def test_unconfirmed_command_raises():
    with pytest.raises(hfd.ProtocolError, match="did not confirm"):
        hfd.Session(FakeLink(status=0), delay=0).send(hfd.command(hfd.START))


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
