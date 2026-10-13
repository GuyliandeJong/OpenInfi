from openinfi import desktop


def test_install_writes_entry_and_icon(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    entry = desktop.install(command="/opt/venv/bin/openinfi")
    text = entry.read_text()
    assert "Exec=/opt/venv/bin/openinfi gui" in text and "Icon=openinfi" in text
    icon = tmp_path / "icons/hicolor/scalable/apps/openinfi.svg"
    assert icon.read_text().startswith("<svg")
    desktop.uninstall()
    assert not entry.exists() and not icon.exists()
