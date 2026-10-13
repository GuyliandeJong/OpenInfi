import pytest

from openinfi import cli, hidkeys
from openinfi import profile as profiles


@pytest.fixture
def run(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def runner(*argv):
        code = cli.main(["--dry-run", *argv])
        return code, capsys.readouterr()

    return runner


def test_bundled_profile_is_consistent():
    prof = profiles.load()
    indices = [k.index for k in prof.keys]
    assert len(indices) == len(set(indices))
    assert all(0 < i < 144 for i in indices)
    assert len({k.name for k in prof.keys}) == len(prof.keys)
    assert prof.protocol == "hfd" and prof.vendor_id == 0x05AC and prof.product_ids == [0x024F]


def test_rgb_mode_dry_run(run):
    code, out = run("rgb", "mode", "breath", "--color", "#0ac81e", "--speed", "4", "--direction", "left")
    assert code == 0
    assert "] 07 0a c8 1e 00 00 00 00 00 04 04 00 00 00 aa 55" in out.err


def test_rgb_keys_and_remap_dry_run(run):
    code, out = run("rgb", "keys", "ESC=red", "#56=0,0,255")
    assert code == 0 and "] 04 23" in out.err and "01 ff 00 00" in out.err and "38 00 00 ff" in out.err
    code, out = run("remap", "CAPS", "lctrl")
    assert code == 0 and "02 01 00 00" in out.err and "CAPS -> lctrl" in out.out


def test_unknown_key_is_an_error(run):
    code, out = run("remap", "NOPE", "esc")
    assert code == 2 and "no key named" in out.err


def test_hidkeys():
    assert hidkeys.code("a") == 0x04
    assert hidkeys.code("Esc") == hidkeys.code("escape") == 0x29
    assert hidkeys.code("0x68") == hidkeys.code("f13")
    assert hidkeys.name(0xE0) == "lctrl"


def test_capture_analyze_names_hfd_commands(capsys, tmp_path):
    path = tmp_path / "r.txt"
    path.write_text("# interface 3\n04 18\n04 11 00 00 00 00 00 00 09\n")
    code = cli.main(["capture", "analyze", str(path)])
    out = capsys.readouterr().out
    assert code == 0 and "start" in out and "keymap, 9 data packet(s)" in out


def test_replay_sends_padded_packets(run, tmp_path):
    path = tmp_path / "r.txt"
    path.write_text("# interface 3\n04 18\n04 02\n")
    code, out = run("replay", str(path))
    assert code == 0 and out.err.count("[dry-run if=3 feature] 04 ") == 2
    assert "sent 2 packets" in out.err


def test_missing_capture_file_is_an_error(capsys, tmp_path):
    code = cli.main(["capture", "analyze", str(tmp_path / "missing.pcapng")])
    assert code == 2 and "No such file" in capsys.readouterr().err
