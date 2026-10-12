from infi75 import cli, hidkeys
from infi75 import profile as profiles


def run(capsys, *argv):
    code = cli.main(["--dry-run", *argv])
    return code, capsys.readouterr()


def test_bundled_profile_is_consistent():
    prof = profiles.load()
    indices = [k.index for k in prof.keys]
    assert len(indices) == len(set(indices))
    assert all(0 <= i < prof.rgb_slots for i in indices)
    assert len({k.name for k in prof.keys}) == len(prof.keys)


def test_rgb_mode_dry_run(capsys):
    code, out = run(capsys, "rgb", "mode", "breathing", "--color", "#0ac81e", "--speed", "4",
                    "--direction", "left")
    assert code == 0
    assert "07 02 04 04 17 0a c8 1e e7" in out.err


def test_rgb_keys_and_remap_dry_run(capsys):
    code, out = run(capsys, "rgb", "keys", "ESC=red", "#41=0,0,255")
    assert code == 0 and out.err.count("[dry-run") == 8
    code, out = run(capsys, "remap", "CAPS", "lctrl")
    assert code == 0 and "13 00 03 00 00 00 00 e9 00 00 e0" in out.err


def test_screen_image_requires_size(capsys, tmp_path):
    from PIL import Image

    path = tmp_path / "x.png"
    Image.new("RGB", (10, 10), "red").save(path)
    code, out = run(capsys, "screen", "image", str(path))
    assert code == 2 and "screen size unknown" in out.err
    code, out = run(capsys, "screen", "image", str(path), "--size", "8x4")
    assert code == 0 and out.err.count("[dry-run") == 3  # start + 64 bytes in 2 packets


def test_unknown_key_is_an_error(capsys):
    code, out = run(capsys, "remap", "NOPE", "esc")
    assert code == 2 and "no key named" in out.err


def test_hidkeys():
    assert hidkeys.code("a") == 0x04
    assert hidkeys.code("Esc") == hidkeys.code("escape") == 0x29
    assert hidkeys.code("0x68") == hidkeys.code("f13")
    assert hidkeys.name(0xE0) == "lctrl"


def test_capture_analyze(capsys, tmp_path):
    path = tmp_path / "r.txt"
    path.write_text("# interface 2\na5 00 01 00 20 fd 00 3d 00 00 a2 ad\n")
    code = cli.main(["capture", "analyze", str(path)])
    out = capsys.readouterr().out
    assert code == 0 and "32400 RGB565 pixels" in out and "240x135" in out


def test_replay_pads_text_and_prefixes_captured_report_id_zero(capsys, tmp_path):
    from infi75 import capture
    from infi75.device import _hidapi_buffer

    assert _hidapi_buffer(capture.Report(b"\x07\x01", kind="text"), 64) == b"\x07\x01" + bytes(62)
    assert _hidapi_buffer(capture.Report(b"\x07\x01", kind="feature", report_id=0), 64) == b"\x00\x07\x01"
    assert _hidapi_buffer(capture.Report(b"\x06\x01", kind="feature", report_id=6), 64) == b"\x06\x01"
    path = tmp_path / "r.txt"
    path.write_text("# interface 1\n07 01\n# interface 2\n28 00\n")
    code, out = run(capsys, "replay", str(path))
    assert code == 0 and "[dry-run if=1 feature]" in out.err and "[dry-run if=2 feature]" in out.err
