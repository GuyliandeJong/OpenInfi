"""Keep the keyboard clock in sync: a systemd user timer plus a plug-in trigger.

The INFI75 clock drifts and has no way to fetch the time itself, so the
computer has to set it. ``install()`` writes two user units:

* ``infi75-clock.service`` runs ``infi75 clock sync --if-present`` once;
* ``infi75-clock.timer`` starts it shortly after login and then at a fixed
  interval.

The udev rule from ``infi75 udev`` additionally asks the user's systemd
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

SERVICE = "infi75-clock.service"
TIMER = "infi75-clock.timer"
DEFAULT_EVERY = "6h"


def unit_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "systemd" / "user"


def executable() -> str:
    """Absolute path of the ``infi75`` command, so the units work outside the virtual environment."""
    sibling = Path(sys.executable).parent / "infi75"  # the script of this (virtual) environment
    if sibling.exists():
        return str(sibling.absolute())
    found = shutil.which("infi75")
    if found:
        return str(Path(found).absolute())
    return f"{sys.executable} -m infi75"


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
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", TIMER)
    return folder


def uninstall() -> None:
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
