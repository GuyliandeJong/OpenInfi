"""Desktop integration: a launcher entry and icon for the graphical app."""

from __future__ import annotations

import os
import shutil
from importlib.resources import files
from pathlib import Path

from .clock import executable

APP_ID = "infi75"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def entry_text(command: str, icon: str = APP_ID) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=INFI75 Configurator\n"
        "GenericName=Keyboard configurator\n"
        "Comment=Lighting, key colours, remapping and screen of the Infiverse INFI75\n"
        f"Exec={command} gui\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Settings;HardwareSettings;Utility;\n"
        "Keywords=keyboard;rgb;remap;infi75;\n"
        "StartupWMClass=INFI75 Configurator\n"
    )


def icon_source() -> Path:
    return Path(str(files("infi75.data").joinpath("infi75.svg")))


def install(command: str | None = None) -> Path:
    base = data_home()
    entry = base / "applications" / f"{APP_ID}.desktop"
    icon = base / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
    entry.parent.mkdir(parents=True, exist_ok=True)
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icon_source(), icon)
    entry.write_text(entry_text(command or executable()))
    return entry


def uninstall() -> None:
    base = data_home()
    (base / "applications" / f"{APP_ID}.desktop").unlink(missing_ok=True)
    (base / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg").unlink(missing_ok=True)
