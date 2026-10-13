"""The five pages of the configurator."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import hfd, screen
from . import theme
from .widgets import ColorPicker, KeyboardView, KeyCapture, button, card, muted, section

# Effect catalogue as presented to the user. Behaviour notes come from tests
# on an INFI75-1.2; "colour" and "direction" mark the controls an effect uses.
EFFECTS = [
    ("Static", [
        ("static", "Static", "One steady colour", True, False),
        ("breath", "Breathing", "Slowly fades in and out", True, False),
        ("glittering", "Soft glow", "Dimmed steady colour", True, False),
    ]),
    ("Animated", [
        ("spectrum", "Spectrum", "Colours roll across the keys", True, False),
        ("colourful", "Colourful", "Random rainbow colours", False, False),
        ("falling", "Rainfall", "Random keys blink like rain", True, False),
        ("flowing", "Flowing", "Rows sweep across the keys", True, True),
        ("shuttle", "Shuttle", "A sweep from right to left", True, True),
        ("pulsating", "Twinkle wave", "Twinkles running across", True, False),
        ("tilt", "Fast twinkle", "Faster twinkle wave", True, True),
        ("outward", "Outward", "Pulsing", True, False),
        ("scrolling", "Scrolling", "Pulsing", True, True),
        ("rolling", "Rolling", "Fast pulsing", True, True),
        ("rotating", "Rotating", "Pulsing", True, False),
        ("explode", "Explode", "Pulsing", True, False),
    ]),
    ("Reactive", [
        ("single-on", "Light on press", "Keys light up when pressed", True, False),
        ("single-off", "Dark on press", "Keys go dark when pressed", True, False),
        ("launch", "Launch", "Pulse from each pressed key", True, False),
        ("ripples", "Ripples", "Faster pulse from each key", True, False),
    ]),
    ("Other", [
        ("effect-0", "Factory pattern", "Built-in blue pattern", False, False),
    ]),
]
EFFECT_INFO = {key: (label, desc, uses_color, uses_dir)
               for _group, items in EFFECTS for key, label, desc, uses_color, uses_dir in items}


class Page(QWidget):
    """Common page frame: title, subtitle and a content area."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(16)
        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        head.addWidget(t)
        s = QLabel(subtitle)
        s.setObjectName("PageSubtitle")
        s.setWordWrap(True)
        head.addWidget(s)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        outer.addLayout(self.body, 1)


def _level_slider(left: str, right: str) -> tuple[QWidget, QSlider, QLabel]:
    box = QWidget()
    layout = QGridLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(8)
    layout.setVerticalSpacing(2)
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, hfd.MAX_LEVEL)
    slider.setPageStep(1)
    slider.setTickPosition(QSlider.NoTicks)
    value = QLabel()
    value.setFixedWidth(18)
    value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    layout.addWidget(slider, 0, 0, 1, 2)
    layout.addWidget(value, 0, 2)
    lo, hi = QLabel(left), QLabel(right)
    lo.setObjectName("Faint")
    hi.setObjectName("Faint")
    hi.setAlignment(Qt.AlignRight)
    layout.addWidget(lo, 1, 0)
    layout.addWidget(hi, 1, 1)
    slider.valueChanged.connect(lambda v: value.setText(str(v)))
    return box, slider, value


# ------------------------------------------------------------------ lighting


class EffectTile(QPushButton):
    def __init__(self, key: str, label: str, desc: str) -> None:
        super().__init__()
        self.key = key
        self.setObjectName("EffectTile")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(62)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(1)
        name = QLabel(label)
        name.setStyleSheet("font-weight:600; background:transparent;")
        sub = QLabel(desc)
        sub.setStyleSheet(f"color:{theme.MUTED}; font-size:9pt; background:transparent;")
        for w in (name, sub):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(w)
        self.setToolTip(f"Firmware effect: {key}")


class LightingPage(Page):
    apply_requested = Signal(dict)

    def __init__(self, saved: dict) -> None:
        super().__init__("Lighting", "Choose an effect and tune it. Changes are sent to the keyboard "
                                     "automatically.")
        row = QHBoxLayout()
        row.setSpacing(16)
        self.body.addLayout(row, 1)

        # effect tiles
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        tiles = QVBoxLayout(holder)
        tiles.setContentsMargins(0, 0, 8, 0)
        tiles.setSpacing(8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.tiles: dict[str, EffectTile] = {}
        for title, items in EFFECTS:
            tiles.addWidget(section(title))
            grid = QGridLayout()
            grid.setSpacing(8)
            for n, (key, label, desc, _c, _d) in enumerate(items):
                tile = EffectTile(key, label, desc)
                self.group.addButton(tile)
                self.tiles[key] = tile
                grid.addWidget(tile, n // 3, n % 3)
            tiles.addLayout(grid)
            tiles.addSpacing(6)
        tiles.addStretch(1)
        scroll.setWidget(holder)
        row.addWidget(scroll, 1)

        # inspector
        inspector, side = card()
        inspector.setFixedWidth(330)
        row.addWidget(inspector)
        self.effect_title = QLabel()
        self.effect_title.setObjectName("CardTitle")
        side.addWidget(self.effect_title)
        self.effect_desc = muted("")
        side.addWidget(self.effect_desc)
        side.addSpacing(4)

        side.addWidget(section("Colour"))
        self.picker = ColorPicker()
        self.picker.setMinimumHeight(230)
        side.addWidget(self.picker)
        self.rainbow = QCheckBox("Rainbow colours")
        side.addWidget(self.rainbow)

        side.addWidget(section("Brightness"))
        box, self.brightness, _ = _level_slider("Dim", "Bright")
        side.addWidget(box)
        side.addWidget(section("Speed"))
        box, self.speed, _ = _level_slider("Slow", "Fast")
        side.addWidget(box)

        side.addWidget(section("Direction"))
        dirs = QHBoxLayout()
        dirs.setSpacing(6)
        self.direction = QButtonGroup(self)
        self.dir_buttons: dict[str, QPushButton] = {}
        for name, glyph in (("left", "←"), ("up", "↑"), ("down", "↓"), ("right", "→")):
            b = QPushButton(glyph)
            b.setCheckable(True)
            b.setFixedSize(46, 34)
            b.setToolTip(name)
            b.setCursor(Qt.PointingHandCursor)
            self.direction.addButton(b)
            self.dir_buttons[name] = b
            dirs.addWidget(b)
        dirs.addStretch(1)
        side.addLayout(dirs)
        side.addStretch(1)

        bottom = QHBoxLayout()
        self.auto = QCheckBox("Apply automatically")
        self.auto.setChecked(True)
        bottom.addWidget(self.auto)
        bottom.addStretch(1)
        side.addLayout(bottom)
        actions = QHBoxLayout()
        self.off_button = button("Lights off")
        self.apply_button = button("Apply", primary=True)
        actions.addWidget(self.off_button)
        actions.addStretch(1)
        actions.addWidget(self.apply_button)
        side.addLayout(actions)

        # state
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self._emit)
        self._restoring = True
        effect = saved.get("effect", "static")
        effect = effect if effect in self.tiles else "static"
        self.tiles[effect].setChecked(True)
        self.picker.set_color(tuple(saved.get("color", (255, 255, 255))))
        self.rainbow.setChecked(bool(saved.get("rainbow", False)))
        self.brightness.setValue(int(saved.get("brightness", 5)))
        self.speed.setValue(int(saved.get("speed", 3)))
        self.dir_buttons.get(saved.get("direction", "right"), self.dir_buttons["right"]).setChecked(True)
        self._restoring = False
        self._sync_controls()

        self.group.buttonClicked.connect(lambda _b: self._changed())
        self.picker.colorCommitted.connect(lambda _c: self._changed(prefer_color=True))
        self.rainbow.toggled.connect(lambda _v: self._changed())
        for slider in (self.brightness, self.speed):
            slider.sliderReleased.connect(self._changed)
            slider.valueChanged.connect(lambda _v, s=slider: None if s.isSliderDown() else self._changed())
        self.direction.buttonClicked.connect(lambda _b: self._changed())
        self.apply_button.clicked.connect(self._emit)
        self.off_button.clicked.connect(lambda: self.apply_requested.emit({"effect": "off"}))
        self.auto.toggled.connect(self._sync_controls)

    def effect(self) -> str:
        checked = self.group.checkedButton()
        return checked.key if checked else "static"

    def settings(self) -> dict:
        direction = next((n for n, b in self.dir_buttons.items() if b.isChecked()), "right")
        return {"effect": self.effect(), "color": self.picker.color(), "rainbow": self.rainbow.isChecked(),
                "brightness": self.brightness.value(), "speed": self.speed.value(), "direction": direction}

    def _sync_controls(self) -> None:
        label, desc, uses_color, uses_dir = EFFECT_INFO[self.effect()]
        self.effect_title.setText(label)
        self.effect_desc.setText(desc + ".")
        self.picker.setEnabled(uses_color and not self.rainbow.isChecked())
        self.rainbow.setEnabled(uses_color)
        for b in self.dir_buttons.values():
            b.setEnabled(uses_dir)
        self.apply_button.setVisible(not self.auto.isChecked())

    def _changed(self, prefer_color: bool = False) -> None:
        if self._restoring:
            return
        if prefer_color and self.rainbow.isChecked():
            self.rainbow.setChecked(False)
        self._sync_controls()
        if self.auto.isChecked():
            self._debounce.start()

    def _emit(self) -> None:
        self.apply_requested.emit(self.settings())


# ---------------------------------------------------------------- key colours


class ColoursPage(Page):
    apply_requested = Signal(dict, tuple, int)

    def __init__(self, profile, colors: dict, default: tuple) -> None:
        super().__init__("Key colours", "Select keys on the keyboard, then pick a colour. Drag to select a "
                                        "group, Shift-click to add keys.")
        self.profile = profile
        self.saved = (dict(colors), tuple(default))
        row = QHBoxLayout()
        row.setSpacing(16)
        self.body.addLayout(row, 1)

        left = QVBoxLayout()
        left.setSpacing(10)
        row.addLayout(left, 1)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(section("Select"))
        for text, picker in (("All", lambda: [k.name for k in profile.keys]),
                             ("Letters", lambda: [k.name for k in profile.keys if len(k.name) == 1 and k.name.isalpha()]),
                             ("Numbers", lambda: [k.name for k in profile.keys if k.name.isdigit()]),
                             ("F-row", lambda: [k.name for k in profile.keys if k.row == 0]),
                             ("WASD", lambda: ["W", "A", "S", "D"]),
                             ("Arrows", lambda: ["UP", "DOWN", "LEFT", "RIGHT"]),
                             ("None", lambda: [])):
            b = button(text, flat=True)
            b.clicked.connect(lambda _=False, p=picker: self.keyboard.set_selection(p()))
            tools.addWidget(b)
        tools.addStretch(1)
        left.addLayout(tools)

        self.keyboard = KeyboardView(profile)
        self.keyboard.colors = dict(colors)
        self.keyboard.default_color = tuple(default)
        left.addWidget(self.keyboard)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        presets.addWidget(section("Presets"))
        for text, fn in (("Rainbow", self._preset_rainbow), ("Gaming", self._preset_gaming),
                         ("Rows", self._preset_rows), ("Single colour", self._preset_single),
                         ("All off", self._preset_off)):
            b = button(text)
            b.clicked.connect(fn)
            presets.addWidget(b)
        presets.addStretch(1)
        left.addLayout(presets)
        left.addStretch(1)

        side, side_layout = card("Brush")
        side.setFixedWidth(300)
        row.addWidget(side)
        self.picker = ColorPicker()
        self.picker.setMinimumHeight(230)
        self.picker.set_color((255, 0, 0))
        side_layout.addWidget(self.picker)
        self.paint_button = button("Paint selected keys", primary=False)
        side_layout.addWidget(self.paint_button)
        side_layout.addWidget(muted("Tip: with keys selected, clicking a colour paints them straight away."))
        side_layout.addSpacing(6)
        side_layout.addWidget(section("Other keys"))
        other = QHBoxLayout()
        self.default_swatch = QPushButton()
        self.default_swatch.setFixedSize(30, 30)
        self.default_swatch.setCursor(Qt.PointingHandCursor)
        self.default_swatch.setToolTip("Use the brush colour for every unpainted key")
        other.addWidget(self.default_swatch)
        other.addWidget(muted("Unpainted keys get this colour. Click to use the brush colour."))
        side_layout.addLayout(other)
        side_layout.addWidget(section("Brightness"))
        box, self.brightness, _ = _level_slider("Dim", "Bright")
        self.brightness.setValue(5)
        side_layout.addWidget(box)
        side_layout.addStretch(1)

        footer = QHBoxLayout()
        self.status = muted("", wrap=False)
        footer.addWidget(self.status)
        footer.addStretch(1)
        self.revert_button = button("Revert")
        self.apply_button = button("Apply to keyboard", primary=True)
        footer.addWidget(self.revert_button)
        footer.addWidget(self.apply_button)
        self.body.addLayout(footer)

        self.keyboard.selectionChanged.connect(self._update_status)
        self.picker.colorCommitted.connect(self._auto_paint)
        self.paint_button.clicked.connect(lambda: self._paint(self.keyboard.selected))
        self.default_swatch.clicked.connect(self._set_default_from_brush)
        self.revert_button.clicked.connect(self._revert)
        self.apply_button.clicked.connect(self._apply)
        self._refresh()

    # editing helpers
    def _paint(self, names, color=None) -> None:
        color = tuple(color or self.picker.color())
        for name in names:
            self.keyboard.colors[name] = color
        self._refresh()

    def _auto_paint(self, color) -> None:
        if self.keyboard.selected:
            self._paint(self.keyboard.selected, color)

    def _set_default_from_brush(self) -> None:
        self.keyboard.default_color = self.picker.color()
        self._refresh()

    def _preset_single(self) -> None:
        self.keyboard.colors = {}
        self.keyboard.default_color = self.picker.color()
        self._refresh()

    def _preset_off(self) -> None:
        self.keyboard.colors = {}
        self.keyboard.default_color = (0, 0, 0)
        self._refresh()

    def _preset_gaming(self) -> None:
        self.keyboard.colors = {k: (255, 0, 0) for k in ("W", "A", "S", "D")}
        self.keyboard.colors.update({k: (255, 160, 0) for k in ("Q", "E", "R", "F", "SPACE", "LSHIFT", "LCTRL")})
        self.keyboard.colors.update({k: (255, 255, 255) for k in ("1", "2", "3", "4", "5")})
        self.keyboard.default_color = (0, 0, 40)
        self._refresh()

    def _preset_rows(self) -> None:
        palette = [(255, 0, 0), (255, 120, 0), (255, 220, 0), (0, 255, 60), (0, 120, 255), (160, 0, 255)]
        self.keyboard.colors = {k.name: palette[k.row % len(palette)] for k in self.profile.keys}
        self._refresh()

    def _preset_rainbow(self) -> None:
        from PySide6.QtGui import QColor

        width = max(k.x + k.w for k in self.profile.keys)
        colors = {}
        for k in self.profile.keys:
            c = QColor.fromHsvF(min(0.999, (k.x + k.w / 2) / width * 0.85), 1, 1)
            colors[k.name] = (c.red(), c.green(), c.blue())
        self.keyboard.colors = colors
        self._refresh()

    def _revert(self) -> None:
        self.keyboard.colors, self.keyboard.default_color = dict(self.saved[0]), tuple(self.saved[1])
        self._refresh()

    def _apply(self) -> None:
        self.apply_requested.emit(dict(self.keyboard.colors), tuple(self.keyboard.default_color or (0, 0, 0)),
                                  self.brightness.value())

    def applied(self) -> None:
        self.saved = (dict(self.keyboard.colors), tuple(self.keyboard.default_color or (0, 0, 0)))
        self._refresh()

    def dirty(self) -> bool:
        return (self.keyboard.colors, tuple(self.keyboard.default_color or (0, 0, 0))) != \
            (self.saved[0], tuple(self.saved[1]))

    def _refresh(self) -> None:
        d = self.keyboard.default_color or (0, 0, 0)
        self.default_swatch.setStyleSheet(
            f"background:rgb{tuple(d)}; border:1px solid {theme.BORDER}; border-radius:8px;")
        self.keyboard.update()
        self._update_status()

    def _update_status(self) -> None:
        n = len(self.keyboard.selected)
        parts = [f"{n} key{'s' if n != 1 else ''} selected" if n else "No keys selected"]
        if self.dirty():
            parts.append("unsaved changes")
        self.status.setText("  ·  ".join(parts))
        self.apply_button.setEnabled(self.dirty())
        self.revert_button.setEnabled(self.dirty())
        self.paint_button.setEnabled(n > 0)


# --------------------------------------------------------------------- remap

TARGET_GROUPS = [
    ("Media", [("volup", "Volume up"), ("voldown", "Volume down"), ("mute", "Mute"),
               ("playpause", "Play / pause"), ("next", "Next track"), ("prev", "Previous track"),
               ("stop", "Stop")]),
    ("Modifiers", [("lctrl", "Left Ctrl"), ("lshift", "Left Shift"), ("lalt", "Left Alt"),
                   ("lgui", "Left Super"), ("rctrl", "Right Ctrl"), ("rshift", "Right Shift"),
                   ("ralt", "Right Alt"), ("rgui", "Right Super")]),
    ("Editing", [("esc", "Escape"), ("enter", "Enter"), ("tab", "Tab"), ("backspace", "Backspace"),
                 ("delete", "Delete"), ("insert", "Insert"), ("space", "Space"), ("capslock", "Caps Lock")]),
    ("Navigation", [("up", "Arrow up"), ("down", "Arrow down"), ("left", "Arrow left"), ("right", "Arrow right"),
                    ("home", "Home"), ("end", "End"), ("pageup", "Page up"), ("pagedown", "Page down")]),
    ("Function keys", [(f"f{i}", f"F{i}") for i in range(1, 25)]),
    ("Letters", [(c, c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"]),
    ("Numbers and symbols", [*((str(n), str(n)) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)),
                             ("minus", "-"), ("equal", "="), ("lbracket", "["), ("rbracket", "]"),
                             ("backslash", "\\"), ("semicolon", ";"), ("quote", "'"), ("grave", "`"),
                             ("comma", ","), ("dot", "."), ("slash", "/")]),
    ("System", [("printscreen", "Print Screen"), ("scrolllock", "Scroll Lock"), ("pause", "Pause"),
                ("menu", "Menu"), ("numlock", "Num Lock")]),
]
_LABELS = {key: label for _group, items in TARGET_GROUPS for key, label in items}
_MOD_WORDS = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Super", "gui": "Super"}


def describe_target(target: str) -> str:
    """Human name for a remap target: "ctrl+c" -> "Ctrl + C"."""
    parts = target.split("+")
    words = [_MOD_WORDS.get(p) or _LABELS.get(p) or p.upper() for p in parts]
    return " + ".join(words)


_KEY_TITLES = {"ESC": "Esc", "GRAVE": "`", "MINUS": "-", "EQUAL": "=", "BACKSPACE": "Backspace", "TAB": "Tab",
               "LBRACKET": "[", "RBRACKET": "]", "BACKSLASH": "\\", "CAPS": "Caps Lock", "SEMICOLON": ";",
               "QUOTE": "'", "ENTER": "Enter", "LSHIFT": "Left Shift", "RSHIFT": "Right Shift", "COMMA": ",",
               "DOT": ".", "SLASH": "/", "LCTRL": "Left Ctrl", "LWIN": "Super", "LALT": "Left Alt",
               "SPACE": "Space", "RALT": "Right Alt", "FN": "Fn", "PGUP": "Page Up", "PGDN": "Page Down",
               "UP": "Arrow up", "DOWN": "Arrow down", "LEFT": "Arrow left", "RIGHT": "Arrow right"}


class RemapPage(Page):
    remap_requested = Signal(dict)

    def __init__(self, profile, remaps: dict) -> None:
        super().__init__("Remap keys", "Click a key on the keyboard, then press the key or combination it "
                                       "should produce.")
        self.profile = profile
        self.remaps = dict(remaps)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.body.addLayout(row, 1)

        left = QVBoxLayout()
        row.addLayout(left, 1)
        self.keyboard = KeyboardView(profile, multi=False)
        left.addWidget(self.keyboard)
        active, active_layout = card("Active remaps")
        self.active_list = QListWidget()
        self.active_list.setMaximumHeight(130)
        active_layout.addWidget(self.active_list)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.reset_button = button("Restore all keys", danger=True)
        buttons.addWidget(self.reset_button)
        active_layout.addLayout(buttons)
        left.addWidget(active)
        left.addStretch(1)

        side, side_layout = card()
        side.setFixedWidth(320)
        row.addWidget(side)
        self.key_title = QLabel("No key selected")
        self.key_title.setObjectName("CardTitle")
        side_layout.addWidget(self.key_title)
        self.key_state = muted("Click a key on the keyboard.")
        side_layout.addWidget(self.key_state)
        side_layout.addSpacing(6)
        side_layout.addWidget(section("New function"))
        self.capture = KeyCapture()
        side_layout.addWidget(self.capture)
        side_layout.addWidget(muted("or choose from the list:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search, or type a combination like ctrl+c")
        side_layout.addWidget(self.search)
        self.targets = QListWidget()
        side_layout.addWidget(self.targets, 1)
        self.choice = QLabel("")
        self.choice.setWordWrap(True)
        self.choice.setStyleSheet(f"color:{theme.TEXT}; font-weight:600;")
        side_layout.addWidget(self.choice)
        actions = QHBoxLayout()
        self.restore_button = button("Restore default")
        self.apply_button = button("Apply remap", primary=True)
        actions.addWidget(self.restore_button)
        actions.addStretch(1)
        actions.addWidget(self.apply_button)
        side_layout.addLayout(actions)

        self.pending: str | None = None
        self._fill_targets("")
        self.keyboard.selectionChanged.connect(self._key_selected)
        self.capture.captured.connect(self._set_pending)
        self.search.textChanged.connect(self._fill_targets)
        self.search.returnPressed.connect(lambda: self._set_pending(self.search.text().strip().lower()))
        self.targets.itemClicked.connect(lambda item: item.data(Qt.UserRole) and self._set_pending(
            item.data(Qt.UserRole)))
        self.apply_button.clicked.connect(self._apply)
        self.restore_button.clicked.connect(self._restore)
        self.reset_button.clicked.connect(self._reset)
        self.active_list.itemClicked.connect(lambda item: self.keyboard.set_selection([item.data(Qt.UserRole)]))
        self.set_remaps(self.remaps)
        self._key_selected()

    def _fill_targets(self, text: str) -> None:
        text = text.strip().lower()
        self.targets.clear()
        for group, items in TARGET_GROUPS:
            matches = [(k, l) for k, l in items if not text or text in k or text in l.lower()]
            if not matches:
                continue
            header = QListWidgetItem(group.upper())
            header.setFlags(Qt.NoItemFlags)
            header.setForeground(Qt.gray)
            self.targets.addItem(header)
            for key, label in matches:
                item = QListWidgetItem(f"   {label}")
                item.setData(Qt.UserRole, key)
                self.targets.addItem(item)

    def _selected_key(self) -> str | None:
        return next(iter(self.keyboard.selected), None)

    def _key_selected(self) -> None:
        name = self._selected_key()
        has_key = name is not None
        for w in (self.capture, self.search, self.targets):
            w.setEnabled(has_key)
        self.pending = None
        self.choice.setText("")
        if not has_key:
            self.key_title.setText("No key selected")
            self.key_state.setText("Click a key on the keyboard.")
        else:
            self.key_title.setText(f"{_KEY_TITLES.get(name, name)} key")
            current = self.remaps.get(name)
            self.key_state.setText(f"Currently remapped to {describe_target(current)}." if current
                                   else "Does its normal job.")
        self._sync_buttons()

    def _set_pending(self, target: str) -> None:
        if not target:
            return
        try:
            hfd.key_entry(target)
        except (KeyError, ValueError) as exc:
            self.choice.setText(f"⚠ {exc.args[0] if exc.args else exc}")
            self.pending = None
        else:
            self.pending = target
            self.choice.setText(f"{self._selected_key()} → {describe_target(target)}")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        name = self._selected_key()
        self.apply_button.setEnabled(bool(name and self.pending))
        self.restore_button.setEnabled(bool(name and name in self.remaps))
        self.reset_button.setEnabled(bool(self.remaps))

    def _apply(self) -> None:
        name = self._selected_key()
        if name and self.pending:
            state = dict(self.remaps)
            state[name] = self.pending
            self.remap_requested.emit(state)

    def _restore(self) -> None:
        name = self._selected_key()
        if name in self.remaps:
            state = dict(self.remaps)
            state.pop(name)
            self.remap_requested.emit(state)

    def _reset(self) -> None:
        self.remap_requested.emit({})

    def set_remaps(self, remaps: dict) -> None:
        self.remaps = dict(remaps)
        self.keyboard.badges = {k: describe_target(v) for k, v in self.remaps.items()}
        self.keyboard.update()
        self.active_list.clear()
        for name, target in sorted(self.remaps.items()):
            item = QListWidgetItem(f"{_KEY_TITLES.get(name, name)}  →  {describe_target(target)}")
            item.setData(Qt.UserRole, name)
            self.active_list.addItem(item)
        if not self.remaps:
            item = QListWidgetItem("No remaps; every key does what its label says.")
            item.setFlags(Qt.NoItemFlags)
            self.active_list.addItem(item)
        self._key_selected()


# -------------------------------------------------------------------- screen


class DropZone(QFrame):
    dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.setStyleSheet(f"QFrame {{ border: 2px dashed {theme.BORDER}; border-radius: 12px; }}")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        title = QLabel("Drop an image or GIF here")
        title.setStyleSheet("border:none; font-weight:600;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        self.browse = button("Browse files...")
        self.browse.setStyleSheet("")
        layout.addWidget(self.browse, 0, Qt.AlignCenter)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.dropped.emit(urls[0].toLocalFile())


class ScreenPage(Page):
    upload_requested = Signal(str, str)
    sync_requested = Signal()

    SCALE = 1.6

    def __init__(self) -> None:
        super().__init__("Screen", "Show your own picture or animation on the keyboard's display, and keep its "
                                   "clock in sync.")
        row = QHBoxLayout()
        row.setSpacing(16)
        self.body.addLayout(row, 1)

        bezel = QFrame()
        bezel.setStyleSheet("QFrame { background:#0b0c0f; border:1px solid #2c2f36; border-radius:18px; }")
        bezel_layout = QVBoxLayout(bezel)
        bezel_layout.setContentsMargins(18, 18, 18, 14)
        self.view = QLabel()
        w, h = int(hfd.SCREEN_WIDTH * self.SCALE), int(hfd.SCREEN_HEIGHT * self.SCALE)
        self.view.setFixedSize(w, h)
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setStyleSheet("background:#000; border:none; border-radius:4px; color:#555;")
        self.view.setText("No image")
        bezel_layout.addWidget(self.view, 0, Qt.AlignCenter)
        self.view_info = QLabel(f"{hfd.SCREEN_WIDTH} × {hfd.SCREEN_HEIGHT} px")
        self.view_info.setObjectName("Faint")
        self.view_info.setAlignment(Qt.AlignCenter)
        self.view_info.setStyleSheet("border:none;")
        bezel_layout.addWidget(self.view_info)
        column = QVBoxLayout()
        column.addWidget(bezel)
        column.addWidget(muted("Preview of the keyboard screen", wrap=False), 0, Qt.AlignHCenter)
        column.addStretch(1)
        row.addLayout(column)

        right = QVBoxLayout()
        right.setSpacing(14)
        row.addLayout(right, 1)
        image_card, image_layout = card("Picture")
        self.drop = DropZone()
        image_layout.addWidget(self.drop)
        self.file_label = muted("PNG, JPG, BMP, WebP or an animated GIF (up to 141 frames).")
        image_layout.addWidget(self.file_label)
        image_layout.addWidget(section("Fit"))
        fits = QHBoxLayout()
        self.fit_group = QButtonGroup(self)
        self.fit_buttons: dict[str, QPushButton] = {}
        for key, text, tip in (("crop", "Fill", "Fill the screen, cropping the edges"),
                               ("pad", "Fit", "Show the whole picture with black bars"),
                               ("stretch", "Stretch", "Stretch to the screen size")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            self.fit_group.addButton(b)
            self.fit_buttons[key] = b
            fits.addWidget(b)
        fits.addStretch(1)
        self.fit_buttons["crop"].setChecked(True)
        image_layout.addLayout(fits)
        upload_row = QHBoxLayout()
        self.upload_button = button("Send to keyboard", primary=True)
        self.upload_button.setEnabled(False)
        upload_row.addWidget(self.upload_button)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.hide()
        upload_row.addWidget(self.progress, 1)
        image_layout.addLayout(upload_row)
        right.addWidget(image_card)

        clock_card, clock_layout = card("Clock")
        self.clock = QLabel()
        self.clock.setStyleSheet("font-size:20pt; font-weight:600;")
        clock_layout.addWidget(self.clock)
        clock_layout.addWidget(muted("The keyboard keeps its own clock. Sync it with this computer when it "
                                     "drifts or after the battery ran empty."))
        self.sync_button = button("Sync clock now")
        clock_layout.addWidget(self.sync_button, 0, Qt.AlignLeft)
        right.addWidget(clock_card)
        right.addStretch(1)

        self.path: str | None = None
        self.frames: list[tuple[QPixmap, int]] = []
        self.frame_index = 0
        self.anim = QTimer(self)
        self.anim.setSingleShot(True)
        self.anim.timeout.connect(self._next_frame)
        tick = QTimer(self)
        tick.timeout.connect(self._tick)
        tick.start(1000)
        self._tick()

        self.drop.dropped.connect(self.load)
        self.drop.browse.clicked.connect(self._browse)
        self.fit_group.buttonClicked.connect(lambda _b: self._render())
        self.upload_button.clicked.connect(lambda: self.path and self.upload_requested.emit(self.path, self.fit()))
        self.sync_button.clicked.connect(self.sync_requested.emit)

    def fit(self) -> str:
        return next(k for k, b in self.fit_buttons.items() if b.isChecked())

    def _tick(self) -> None:
        self.clock.setText(datetime.now().strftime("%H:%M:%S   %a %d %b"))

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a picture", str(Path.home()),
                                              "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        self.path = path
        self._render()

    def _render(self) -> None:
        if not self.path:
            return
        try:
            frames = screen.preview_frames(self.path, hfd.SCREEN_WIDTH, hfd.SCREEN_HEIGHT,
                                           hfd.SCREEN_MAX_FRAMES, self.fit())
        except OSError as exc:
            self.file_label.setText(f"⚠ Cannot open this file: {exc}")
            self.upload_button.setEnabled(False)
            return
        size = QSize(self.view.width(), self.view.height())
        self.frames = []
        for image, duration in frames:
            data = image.tobytes()
            qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(qimage).scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.frames.append((pixmap, max(20, min(510, duration))))
        name = os.path.basename(self.path)
        count = len(self.frames)
        self.file_label.setText(f"{name}  ·  {count} frame{'s' if count != 1 else ''}")
        self.view_info.setText(f"{hfd.SCREEN_WIDTH} × {hfd.SCREEN_HEIGHT} px"
                               + (f"  ·  {count} frames" if count > 1 else ""))
        self.upload_button.setEnabled(True)
        self.frame_index = 0
        self.anim.stop()
        self._next_frame()

    def _next_frame(self) -> None:
        if not self.frames:
            return
        pixmap, duration = self.frames[self.frame_index % len(self.frames)]
        self.view.setPixmap(pixmap)
        self.frame_index += 1
        if len(self.frames) > 1:
            self.anim.start(duration)

    def set_progress(self, done: int, total: int) -> None:
        self.progress.show()
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def upload_finished(self) -> None:
        self.progress.hide()


# -------------------------------------------------------------------- device


class DevicePage(Page):
    check_requested = Signal()
    simulate_toggled = Signal(bool)

    UDEV_COMMAND = ("infi75 udev | sudo tee /etc/udev/rules.d/70-infi75.rules && "
                    "sudo udevadm control --reload && sudo udevadm trigger")

    def __init__(self, profile, simulate: bool) -> None:
        super().__init__("Device", "Connection details, permissions and troubleshooting.")
        grid = QGridLayout()
        grid.setSpacing(16)
        self.body.addLayout(grid, 1)

        status, status_layout = card("Keyboard")
        self.rows: dict[str, QLabel] = {}
        form = QGridLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(8)
        for n, (key, label) in enumerate((("connection", "Connection"), ("model", "Model"),
                                          ("usb", "USB ID"), ("firmware", "Firmware"),
                                          ("config", "Settings channel"), ("screen", "Screen channel"),
                                          ("udev", "Permission rule"))):
            name = muted(label, wrap=False)
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addWidget(name, n, 0)
            form.addWidget(value, n, 1)
            self.rows[key] = value
        form.setColumnStretch(1, 1)
        status_layout.addLayout(form)
        self.check_button = button("Run check")
        status_layout.addWidget(self.check_button, 0, Qt.AlignLeft)
        grid.addWidget(status, 0, 0)

        perms, perms_layout = card("Permissions",
                                   "Linux needs a one-time rule so this app may talk to the keyboard without "
                                   "root. Run this in a terminal, then unplug and replug the cable:")
        command = QLineEdit(self.UDEV_COMMAND)
        command.setReadOnly(True)
        command.setCursorPosition(0)
        perms_layout.addWidget(command)
        copy = button("Copy command")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.UDEV_COMMAND))
        perms_layout.addWidget(copy, 0, Qt.AlignLeft)
        perms_layout.addSpacing(6)
        perms_layout.addWidget(section("Bluetooth"))
        perms_layout.addWidget(muted("Settings can only be changed over the USB cable in wired mode. Everything "
                                     "you set stays active when you switch back to Bluetooth."))
        perms_layout.addStretch(1)
        grid.addWidget(perms, 0, 1)

        advanced, advanced_layout = card("Advanced")
        self.simulate = QCheckBox("Simulation mode: show the data that would be sent, send nothing")
        self.simulate.setChecked(simulate)
        advanced_layout.addWidget(self.simulate)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("Activity log")
        self.log.setStyleSheet("font-family: monospace; font-size: 8.5pt;")
        advanced_layout.addWidget(self.log, 1)
        grid.addWidget(advanced, 1, 0, 1, 2)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.rows["model"].setText(profile.name)
        self.rows["usb"].setText(f"{profile.vendor_id:04x}:{profile.product_ids[0]:04x}"
                                 if profile.product_ids else f"{profile.vendor_id:04x}")
        self.check_button.clicked.connect(self.check_requested.emit)
        self.simulate.toggled.connect(self.simulate_toggled.emit)

    def show_report(self, report: dict) -> None:
        ok, bad = f"color:{theme.SUCCESS};", f"color:{theme.DANGER};"
        for key, (good, text) in report.items():
            if key in self.rows:
                self.rows[key].setText(text)
                self.rows[key].setStyleSheet(ok if good else bad if good is False else "")

    def append_log(self, line: str) -> None:
        self.log.appendPlainText(line)
