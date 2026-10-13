from infi75 import desktop


def test_install_writes_entry_and_icon(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    entry = desktop.install(command="/opt/venv/bin/infi75")
    text = entry.read_text()
    assert "Exec=/opt/venv/bin/infi75 gui" in text and "Icon=infi75" in text
    icon = tmp_path / "icons/hicolor/scalable/apps/infi75.svg"
    assert icon.read_text().startswith("<svg")
    desktop.uninstall()
    assert not entry.exists() and not icon.exists()
