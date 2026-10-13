"""Entry point for the graphical configurator (Qt, PySide6)."""

from __future__ import annotations

from .transport import DeviceError


def run(args) -> int:
    try:
        from .ui.app import run as run_app
    except ImportError as exc:
        raise DeviceError(
            f"the GUI needs PySide6 ({exc}). Install it with: pip install 'infi75[gui]' "
            "(or: sudo pacman -S pyside6)"
        ) from None
    return run_app(args)
