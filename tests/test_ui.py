import argparse
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from infi75.ui.app import MainWindow

    w = MainWindow(argparse.Namespace(profile=None, vid=None, pid=None, dry_run=True))
    yield w
    w.close()


def wait(app, window, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if not window.busy:
            return
        time.sleep(0.01)
    raise AssertionError("worker did not finish")


def test_simulation_actions_run(app, window):
    logs = []
    window.device.log.textChanged.connect(lambda: logs.append(window.device.log.toPlainText()))
    window.lighting.tiles["spectrum"].click()
    window.lighting._emit()
    wait(app, window)
    window.colours.keyboard.set_selection(["W"])
    window.colours._paint(["W"], (255, 0, 0))
    assert window.colours.dirty()
    window.colours._apply()
    wait(app, window)
    assert not window.colours.dirty()
    window.remap.keyboard.set_selection(["CAPS"])
    window.remap._set_pending("esc")
    window.remap._apply()
    wait(app, window)
    assert window.remap.remaps == {"CAPS": "esc"}
    text = window.device.log.toPlainText()
    assert "ok: Applying lighting" in text and "ok: Applying key colours" in text and "ok: Saving remaps" in text


def test_effect_controls_follow_the_effect(app, window):
    window.lighting.tiles["colourful"].click()
    assert not window.lighting.picker.isEnabled()
    window.lighting.tiles["flowing"].click()
    assert window.lighting.picker.isEnabled() and window.lighting.dir_buttons["left"].isEnabled()
    window.lighting.tiles["static"].click()
    assert not window.lighting.dir_buttons["left"].isEnabled()


def test_key_capture_uses_physical_key(app):
    from infi75.ui.widgets import target_from_event

    ctrl_c = QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier, 46 + 8, 0, 0, "c")
    assert target_from_event(ctrl_c) == "ctrl+c"
    shifted_one = QKeyEvent(QEvent.KeyPress, Qt.Key_Exclam, Qt.ShiftModifier, 2 + 8, 0, 0, "!")
    assert target_from_event(shifted_one) == "shift+1"
    right_alt = QKeyEvent(QEvent.KeyRelease, Qt.Key_Alt, Qt.NoModifier, 108, 0, 0, "")
    assert target_from_event(right_alt) == "ralt"


def test_describe_target():
    from infi75.ui.pages import describe_target

    assert describe_target("ctrl+c") == "Ctrl + C"
    assert describe_target("volup") == "Volume up"
    assert describe_target("lctrl") == "Left Ctrl"


def test_fn_layer_and_reserved_keys(app, window):
    window.remap.layer_buttons["fn"].click()
    window.remap.keyboard.set_selection(["ESC"])
    assert not window.remap.capture.isEnabled()
    assert "Reserved" in window.remap.key_state.text()
    window.remap.keyboard.set_selection(["F1"])
    window.remap._set_pending("mute")
    window.remap._apply()
    wait(app, window)
    assert window.remap.layers["fn"] == {"F1": "mute"} and window.remap.layers["base"] == {}
    assert "ok: Saving remaps" in window.device.log.toPlainText()


def test_settings_page_sends_system_and_lists_setups(app, window):
    window.settings.game_mode.setChecked(True)
    window.settings.blocks["block_win"].setChecked(True)
    window.settings._apply_system()
    wait(app, window)
    assert "ok: Applying game mode and sleep" in window.device.log.toPlainText()
    assert not window.settings.load_button.isEnabled()
    window.settings.set_setups(["Gaming", "Work"])
    window.settings.setup_list.setCurrentRow(1)
    assert window.settings.load_button.isEnabled()


def test_macro_page_validates_and_saves(app, window):
    page = window.macros
    page.name.setText("hello")
    page.sequence.setPlainText("text:hi 50ms enter")
    assert page.save_button.isEnabled() and "h, i, 50 ms, enter" in page.preview.text()
    page.save_button.click()
    wait(app, window)
    assert "ok: Saving macro 'hello'" in window.device.log.toPlainText()
    assert "hello" in window.remap.macro_names
    page.sequence.setPlainText("nosuchkey")
    assert not page.save_button.isEnabled()
