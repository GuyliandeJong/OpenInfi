"""Keep the keyboard clock in sync: a systemd user timer plus a plug-in trigger.

The INFI75 clock drifts and has no way to fetch the time itself, so the
computer has to set it. ``install()`` writes two user units:

* ``openinfi-clock.service`` runs ``openinfi clock sync --if-present`` once;
* ``openinfi-clock.timer`` starts it shortly after login and then at a fixed
  interval.

The udev rule from ``openinfi udev`` additionally asks the user's systemd
instance to start the service whenever the keyboard is plugged in or
switched to wired mode (``ENV{SYSTEMD_USER_WANTS}``, see systemd.device(5)).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE = "openinfi-clock.service"
TIMER = "openinfi-clock.timer"
LEGACY_UNITS = ("infi75-clock.timer", "infi75-clock.service")  # the project's former name
DEFAULT_EVERY = "6h"


def unit_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "systemd" / "user"


def executable() -> str:
    """Absolute path of the ``openinfi`` command, so the units work outside the virtual environment."""
    sibling = Path(sys.executable).parent / "openinfi"  # the script of this (virtual) environment
    if sibling.exists():
        return str(sibling.absolute())
    found = shutil.which("openinfi")
    if found:
        return str(Path(found).absolute())
    return f"{sys.executable} -m openinfi"


def check_interval(every: str) -> str:
    """Accept systemd time spans such as 30min, 1h, 6h, 1d."""
    text = every.strip().lower()
    match = re.fullmatch(r"(\d+)\s*(s|sec|m|min|h|hr|d|day)", text)
    if not match:
        raise ValueError(f"bad interval {every!r}; use e.g. 30min, 1h, 6h, 1d")
    unit = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600, "hr": 3600, "d": 86400, "day": 86400}[match[2]]
    if int(match[1]) * unit < 300:
        raise ValueError("interval must be at least 5min: every sync writes the keyboard's settings memory")
    return text.replace(" ", "")


def service_text(command: str) -> str:
    return (
        "[Unit]\n"
        "Description=Set the INFI75 keyboard clock to the computer's time\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={command} clock sync --if-present --wait 10\n"
    )


def timer_text(every: str) -> str:
    return (
        "[Unit]\n"
        "Description=Keep the INFI75 keyboard clock in sync\n"
        "\n"
        "[Timer]\n"
        "OnStartupSec=30s\n"
        f"OnUnitActiveSec={every}\n"
        "AccuracySec=1min\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def _systemctl(*args: str) -> None:
    if not shutil.which("systemctl"):
        raise RuntimeError("systemctl not found; automatic clock sync needs systemd")
    result = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"systemctl --user {' '.join(args)}: {result.stderr.strip() or result.returncode}")


def install(every: str = DEFAULT_EVERY, command: str | None = None) -> Path:
    every = check_interval(every)
    folder = unit_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SERVICE).write_text(service_text(command or executable()))
    (folder / TIMER).write_text(timer_text(every))
    remove_legacy()
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", TIMER)
    return folder


def remove_legacy() -> bool:
    """Stop and delete clock units installed under the former name (infi75). Returns True if any were found."""
    folder = unit_dir()
    found = [name for name in LEGACY_UNITS if (folder / name).exists()]
    if LEGACY_UNITS[0] in found:
        try:
            _systemctl("disable", "--now", LEGACY_UNITS[0])
        except RuntimeError:
            pass
    for name in found:
        (folder / name).unlink(missing_ok=True)
    return bool(found)


def uninstall() -> None:
    remove_legacy()
    folder = unit_dir()
    if (folder / TIMER).exists():
        try:
            _systemctl("disable", "--now", TIMER)
        except RuntimeError:
            pass
    for name in (TIMER, SERVICE):
        (folder / name).unlink(missing_ok=True)
    try:
        _systemctl("daemon-reload")
    except RuntimeError:
        pass


def installed() -> bool:
    return (unit_dir() / TIMER).exists()


def interval() -> str | None:
    try:
        text = (unit_dir() / TIMER).read_text()
    except OSError:
        return None
    match = re.search(r"^OnUnitActiveSec=(\S+)", text, re.M)
    return match.group(1) if match else None
