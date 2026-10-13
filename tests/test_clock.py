import pytest

from infi75 import cli, clock, hfd
from infi75.transport import udev_rule


@pytest.fixture
def units(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr(clock, "_systemctl", lambda *a: calls.append(a))
    return tmp_path / "systemd" / "user", calls


def test_install_writes_units_and_enables_timer(units):
    folder, calls = units
    clock.install("1h", command="/opt/venv/bin/infi75")
    service = (folder / clock.SERVICE).read_text()
    timer = (folder / clock.TIMER).read_text()
    assert "ExecStart=/opt/venv/bin/infi75 clock sync --if-present --wait 10" in service
    assert "OnUnitActiveSec=1h" in timer and "OnStartupSec=30s" in timer
    assert ("enable", "--now", clock.TIMER) in calls
    assert clock.installed() and clock.interval() == "1h"
    clock.uninstall()
    assert not clock.installed() and not (folder / clock.SERVICE).exists()


@pytest.mark.parametrize("bad", ["often", "10s", "2min", "1 week", ""])
def test_interval_is_validated(bad):
    with pytest.raises(ValueError):
        clock.check_interval(bad)


def test_udev_rule_starts_clock_service_on_plug_in():
    rule = udev_rule(0x05AC, [0x024F])
    line = next(l for l in rule.splitlines() if "SYSTEMD_USER_WANTS" in l)
    assert 'ATTR{product}=="INFI75*"' in line
    assert 'TAG+="systemd"' in line and 'ENV{SYSTEMD_USER_WANTS}+="infi75-clock.service"' in line


def test_sync_without_save_skips_save(capsys):
    class Link:
        sent = []

        def set_feature(self, data, report_id=0):
            self.sent.append(bytes(data))
            return len(data)

        def get_feature(self, report_id=0, length=64):
            return bytes(self.sent[-1][:3]) + b"\x01" + bytes(60)

    link = Link()
    hfd.Session(link, delay=0).sync_time(save=False)
    assert [p[:2].hex() for p in link.sent[:2]] == ["0418", "0428"] and len(link.sent) == 3
    assert not any(p[:2] == b"\x04\x02" for p in link.sent)


def test_clock_sync_dry_run(capsys):
    assert cli.main(["--dry-run", "clock", "sync", "--at", "2026-10-13T09:41:07"]) == 0
    out = capsys.readouterr()
    assert "keyboard clock set to 2026-10-13 09:41:07" in out.out
    assert "04 28" in out.err and "04 02" in out.err
