"""Main window: sidebar navigation, connection state and background work."""

from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import clock, desktop
from .. import profile as profiles
from ..board import InfiBoard
from ..transport import DeviceError
from . import theme
from .pages import ColoursPage, DevicePage, LightingPage, MacrosPage, RemapPage, ScreenPage, SettingsPage
from .widgets import Toast, button


class _Bridge(QObject):
    """Carries results from worker threads back to the UI thread."""

    finished = Signal(object, object)
    failed = Signal(str, str)
    progress = Signal(int, int)
    log = Signal(str)


def friendly_error(exc: BaseException) -> str:
    text = str(exc)
    lower = text.lower()
    if "access denied" in lower or "permission" in lower or "open failed" in lower or "claim" in lower:
        return "No permission to talk to the keyboard. Install the permission rule on the Device page, " \
               "then replug the cable."
    if "not found" in lower or "no such device" in lower:
        return "The keyboard is not connected. Connect the USB cable and switch the keyboard to wired mode."
    if "timeout" in lower or "timed out" in lower:
        return "The keyboard did not answer in time. Replug the cable and try again."
    return text


class StatusDot(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.color = QColor(theme.FAINT)
        self.setFixedSize(10, 10)

    def set_color(self, color: str) -> None:
        self.color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(0, 0, 10, 10)


class MainWindow(QMainWindow):
    def __init__(self, args) -> None:
        super().__init__()
        self.args = args
        self.profile = profiles.load(args.profile)
        if self.profile.protocol != "hfd":
            raise DeviceError("the GUI supports the INFI75 (HFD protocol); use the command line for other boards")
        self.simulate = bool(args.dry_run)
        self.busy = False
        self.queued = None
        self.connection = "none"
        self.bridge = _Bridge()
        self.bridge.finished.connect(self._on_finished)
        self.bridge.failed.connect(self._on_failed)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.log.connect(self._on_log)

        board = self._board()
        colors, default = board.saved_colors()
        self.setWindowTitle("INFI75 Configurator")
        self.resize(1240, 800)
        self.setMinimumSize(1080, 720)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        # sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 20, 0, 16)
        side.setSpacing(4)
        brand = QLabel("INFI75")
        brand.setObjectName("Brand")
        brand.setContentsMargins(20, 0, 0, 0)
        side.addWidget(brand)
        sub = QLabel("Keyboard configurator")
        sub.setObjectName("BrandSub")
        sub.setContentsMargins(20, 0, 0, 0)
        side.addWidget(sub)
        side.addSpacing(16)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(20, 0, 12, 0)
        self.dot = StatusDot()
        status_row.addWidget(self.dot)
        self.status_text = QLabel("Checking...")
        self.status_text.setObjectName("Muted")
        status_row.addWidget(self.status_text, 1)
        side.addLayout(status_row)
        side.addSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        for name in ("Lighting", "Key colours", "Remap keys", "Macros", "Screen", "Settings", "Device"):
            self.nav.addItem(QListWidgetItem(name))
        side.addWidget(self.nav, 1)
        self.sim_chip = QLabel("Simulation mode")
        self.sim_chip.setObjectName("Chip")
        self.sim_chip.setAlignment(Qt.AlignCenter)
        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(16, 0, 16, 0)
        chip_row.addWidget(self.sim_chip)
        side.addLayout(chip_row)
        layout.addWidget(sidebar)

        # content
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(14, 8, 10, 8)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        banner_row.addWidget(self.banner_text, 1)
        retry = button("Check again")
        retry.clicked.connect(self.refresh_connection)
        banner_row.addWidget(retry)
        banner_wrap = QVBoxLayout()
        banner_wrap.setContentsMargins(28, 16, 28, 0)
        banner_wrap.addWidget(self.banner)
        content.addLayout(banner_wrap)

        self.stack = QStackedWidget()
        self.lighting = LightingPage(board.saved_lighting())
        self.colours = ColoursPage(self.profile, colors, default)
        self.remap = RemapPage(self.profile, board.remaps("base"), board.remaps("fn"))
        self.macros = MacrosPage(board.macros())
        self.remap.set_macros([m["name"] for m in board.macros()])
        self.screen = ScreenPage()
        self.settings = SettingsPage(board.system(), board.setups())
        self.device = DevicePage(self.profile, self.simulate)
        for page in (self.lighting, self.colours, self.remap, self.macros, self.screen, self.settings,
                     self.device):
            self.stack.addWidget(page)
        content.addWidget(self.stack, 1)
        holder = QWidget()
        holder.setLayout(content)
        layout.addWidget(holder, 1)

        self.toast = Toast(holder)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.lighting.apply_requested.connect(self.apply_lighting)
        self.colours.apply_requested.connect(self.apply_colours)
        self.remap.remap_requested.connect(self.apply_remaps)
        self.screen.upload_requested.connect(self.upload_image)
        self.screen.sync_requested.connect(self.sync_clock)
        self.screen.set_auto_sync(clock.installed())
        self.screen.auto_sync_toggled.connect(self.set_auto_sync)
        self.macros.save_requested.connect(self.save_macro)
        self.macros.delete_requested.connect(self.delete_macro)
        self.settings.system_requested.connect(self.apply_system)
        self.settings.setup_save_requested.connect(self.save_setup)
        self.settings.setup_apply_requested.connect(self.apply_setup)
        self.settings.setup_delete_requested.connect(self.delete_setup)
        self.device.check_requested.connect(self.run_check)
        self.device.simulate_toggled.connect(self.set_simulate)

        self.poll = QTimer(self)
        self.poll.timeout.connect(self.refresh_connection)
        self.poll.start(4000)
        self.refresh_connection()

    # ---------------------------------------------------------------- state

    def _board(self) -> InfiBoard:
        return InfiBoard(self.profile, self.args.vid, self.args.pid, dry_run=self.simulate,
                         log=self.bridge.log.emit, trace=getattr(self.args, "trace", False))

    def set_simulate(self, on: bool) -> None:
        self.simulate = on
        self.refresh_connection()

    def refresh_connection(self) -> None:
        if self.busy:
            return
        self.connection = "simulation" if self.simulate else self._board().connection()
        text, color, banner = {
            "usb": ("Connected (USB)", theme.SUCCESS, None),
            "simulation": ("Simulation", theme.WARNING, None),
            "bluetooth": ("Bluetooth only", theme.WARNING,
                          "The keyboard is connected over Bluetooth. Connect the USB cable and switch it to wired "
                          "mode to change settings; they stay active over Bluetooth afterwards."),
            "none": ("Not connected", theme.DANGER,
                     "Keyboard not found. Connect the USB cable and switch the keyboard to wired mode. If it is "
                     "connected, check the permission rule on the Device page."),
        }[self.connection]
        self.status_text.setText(text)
        self.dot.set_color(color)
        self.sim_chip.setVisible(self.simulate)
        self.banner.setVisible(banner is not None)
        if banner:
            self.banner_text.setText(banner)

    # ---------------------------------------------------------------- worker

    def run(self, label: str, action, done=None, coalesce: str | None = None) -> None:
        """Run *action(board)* off the UI thread. Lighting changes are coalesced: only the latest waits."""
        if self.connection not in ("usb", "simulation"):
            self.toast.show_message("Connect the keyboard by USB cable first.", "error")
            return
        if self.busy:
            if coalesce:
                self.queued = (label, action, done)
            else:
                self.toast.show_message("Please wait, the keyboard is busy.", "busy")
            return
        self.busy = True
        self.toast.show_message(f"{label}...", "busy", timeout_ms=0)
        board = self._board()

        def work() -> None:
            try:
                result = action(board)
                self.bridge.finished.emit((label, done), result)
            except Exception as exc:  # report every failure in the UI
                self.bridge.failed.emit(label, friendly_error(exc))

        threading.Thread(target=work, daemon=True).start()

    def _next(self) -> None:
        self.busy = False
        if self.queued:
            label, action, done = self.queued
            self.queued = None
            self.run(label, action, done)

    def _on_finished(self, meta, result) -> None:
        label, done = meta
        if done:
            done(result)
        suffix = " (simulated)" if self.simulate else ""
        self.toast.show_message(f"✓ {label} done{suffix}", "ok")
        self.device.append_log(f"ok: {label}")
        self._next()

    def _on_failed(self, label: str, message: str) -> None:
        self.toast.show_message(f"{label} failed: {message}", "error", timeout_ms=7000)
        self.device.append_log(f"error: {label}: {message}")
        self._next()
        self.refresh_connection()

    def _on_progress(self, done: int, total: int) -> None:
        self.screen.set_progress(done, total)
        self.toast.show_message(f"Sending picture... {done * 100 // max(1, total)}%", "busy", timeout_ms=0)

    def _on_log(self, line: str) -> None:
        self.device.append_log(line)

    # --------------------------------------------------------------- actions

    def apply_lighting(self, s: dict) -> None:
        effect = s["effect"]
        label = "Turning lights off" if effect == "off" else "Applying lighting"
        self.run(label, lambda b: b.set_lighting(effect, s.get("color", (255, 255, 255)), s.get("brightness", 5),
                                                 s.get("speed", 3), s.get("rainbow", False),
                                                 s.get("direction", "right")), coalesce="lighting")

    def apply_colours(self, colors: dict, default: tuple, brightness: int) -> None:
        self.run("Applying key colours", lambda b: b.set_key_colors(colors, default=default, brightness=brightness),
                 done=lambda _r: self.colours.applied())

    def apply_remaps(self, layer: str, state: dict) -> None:
        label = "Restoring all keys" if not state else "Saving remaps"
        self.run(label, lambda b: (b.write_remaps(state, layer), state)[1],
                 done=lambda result: self.remap.set_remaps(layer, result))

    def _show_macros(self, macros: list[dict]) -> None:
        self.macros.set_macros(macros)
        self.remap.set_macros([m["name"] for m in macros])

    def save_macro(self, name: str, sequence: str) -> None:
        self.run(f"Saving macro '{name}'", lambda b: b.save_macro(name, sequence), done=self._show_macros)

    def delete_macro(self, name: str) -> None:
        self.run(f"Deleting macro '{name}'", lambda b: b.delete_macro(name), done=self._show_macros)

    def apply_system(self, changes: dict) -> None:
        self.run("Applying game mode and sleep", lambda b: b.set_system(**changes), done=self.settings.set_system)

    def save_setup(self, name: str) -> None:
        try:
            self._board().save_setup(name)
        except (OSError, ValueError) as exc:
            self.toast.show_message(f"Could not save: {exc}", "error", timeout_ms=7000)
            return
        self.settings.set_setups(self._board().setups())
        self.toast.show_message(f"✓ Saved setup '{name}'", "ok")

    def delete_setup(self, name: str) -> None:
        try:
            self._board().delete_setup(name)
        except (OSError, ValueError) as exc:
            self.toast.show_message(f"Could not delete: {exc}", "error", timeout_ms=7000)
            return
        self.settings.set_setups(self._board().setups())

    def apply_setup(self, name: str, include_screen: bool) -> None:
        def done(_result) -> None:
            board = self._board()
            self.lighting.restore(board.saved_lighting())
            self.colours.load(*board.saved_colors())
            self.remap.set_remaps("base", board.remaps("base"))
            self.remap.set_remaps("fn", board.remaps("fn"))
            self.settings.set_system(board.system())
            self._show_macros(board.macros())

        self.run(f"Applying setup '{name}'",
                 lambda b: b.apply_setup(name, include_screen, progress=self.bridge.progress.emit), done=done)

    def upload_image(self, path: str, fit: str) -> None:
        self.run("Sending picture", lambda b: b.upload_image(path, fit=fit, progress=self.bridge.progress.emit),
                 done=lambda _r: self.screen.upload_finished())

    def sync_clock(self) -> None:
        self.run("Syncing clock", lambda b: b.sync_time())

    def set_auto_sync(self, on: bool) -> None:
        try:
            if on:
                clock.install()
                self.toast.show_message("✓ The clock now syncs automatically", "ok")
            else:
                clock.uninstall()
                self.toast.show_message("Automatic clock sync turned off", "ok")
        except (OSError, RuntimeError, ValueError) as exc:
            self.screen.set_auto_sync(clock.installed())
            self.toast.show_message(f"Automatic sync failed: {exc}", "error", timeout_ms=7000)

    def run_check(self) -> None:
        if self.busy:
            return
        self.device.show_report(self._board().diagnose())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.reposition()


def run(args) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("INFI75 Configurator")
    app.setDesktopFileName("infi75")  # matches infi75.desktop, so the task bar shows its icon
    app.setWindowIcon(QIcon(str(desktop.icon_source())))
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLE)
    window = MainWindow(args)
    window.show()
    return app.exec()
