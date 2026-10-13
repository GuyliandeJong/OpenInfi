"""Reusable widgets: colour picker, keyboard view, key capture, toast."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme

SWATCHES = ["#ff0000", "#ff5a00", "#ffc800", "#00ff3c", "#00e5ff", "#0050ff", "#8000ff", "#ff00b4", "#ffffff"]


# ---------------------------------------------------------------- helpers


def card(title: str | None = None, subtitle: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(10)
    if title:
        label = QLabel(title)
        label.setObjectName("CardTitle")
        layout.addWidget(label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        layout.addWidget(sub)
    return frame, layout


def section(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("Section")
    return label


def muted(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(wrap)
    return label


def button(text: str, primary: bool = False, flat: bool = False, danger: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    if primary:
        btn.setProperty("primary", True)
    if flat:
        btn.setProperty("flat", True)
    if danger:
        btn.setProperty("danger", True)
    return btn


def rgb_to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def hex_to_rgb(text: str) -> tuple[int, int, int]:
    text = text.strip().lstrip("#")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def readable_on(color: QColor) -> QColor:
    luma = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return QColor("#111111") if luma > 150 else QColor("#f2f2f2")


# ----------------------------------------------------------- colour picker


class _SVSquare(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.hue, self.sat, self.val = 0.0, 1.0, 1.0
        self.setMinimumSize(180, 130)
        self.setCursor(Qt.CrossCursor)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        p.setClipPath(path)
        p.fillRect(rect, QColor.fromHsvF(self.hue, 1, 1))
        white = QLinearGradient(rect.topLeft(), rect.topRight())
        white.setColorAt(0, QColor(255, 255, 255))
        white.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(rect, white)
        black = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        black.setColorAt(0, QColor(0, 0, 0, 0))
        black.setColorAt(1, QColor(0, 0, 0))
        p.fillRect(rect, black)
        p.setClipping(False)
        x = rect.left() + self.sat * rect.width()
        y = rect.top() + (1 - self.val) * rect.height()
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(QPointF(x, y), 7, 7)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.drawEllipse(QPointF(x, y), 8.5, 8.5)

    def _pick(self, pos) -> None:
        self.sat = min(1, max(0, pos.x() / max(1, self.width())))
        self.val = min(1, max(0, 1 - pos.y() / max(1, self.height())))
        self.update()
        self.changed.emit()

    def mousePressEvent(self, event) -> None:
        self._pick(event.position())

    def mouseMoveEvent(self, event) -> None:
        self._pick(event.position())


class _HueBar(QWidget):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.hue = 0.0
        self.setFixedHeight(16)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 3, -1, -3)
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        for i in range(7):
            grad.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1.0, 1, 1))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(rect, 5, 5)
        x = rect.left() + self.hue * rect.width()
        p.setPen(QPen(QColor("white"), 2))
        p.setBrush(QColor.fromHsvF(self.hue, 1, 1))
        p.drawEllipse(QPointF(x, self.height() / 2), 7, 7)

    def _pick(self, pos) -> None:
        self.hue = min(0.999, max(0, pos.x() / max(1, self.width())))
        self.update()
        self.changed.emit()

    def mousePressEvent(self, event) -> None:
        self._pick(event.position())

    def mouseMoveEvent(self, event) -> None:
        self._pick(event.position())


class ColorPicker(QWidget):
    """Saturation/value square, hue bar, hex field and quick swatches.

    ``colorChanged`` fires continuously while dragging; ``colorCommitted``
    fires when a choice is final (mouse released, swatch clicked, hex entered).
    """

    colorChanged = Signal(tuple)
    colorCommitted = Signal(tuple)

    def __init__(self, compact: bool = False) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.square = _SVSquare()
        if compact:
            self.square.setMinimumHeight(100)
        self.hue = _HueBar()
        layout.addWidget(self.square, 1)
        layout.addWidget(self.hue)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.preview = QLabel()
        self.preview.setFixedSize(30, 30)
        row.addWidget(self.preview)
        self.hex = QLineEdit()
        self.hex.setFixedWidth(84)
        self.hex.setMaxLength(7)
        row.addWidget(self.hex)
        row.addStretch(1)
        layout.addLayout(row)

        swatches = QGridLayout()
        swatches.setSpacing(6)
        for n, color in enumerate(SWATCHES):
            sw = QPushButton()
            sw.setFixedSize(24, 24)
            sw.setCursor(Qt.PointingHandCursor)
            sw.setToolTip(color)
            sw.setStyleSheet(f"background:{color}; border:1px solid {theme.BORDER}; border-radius:12px; padding:0;")
            sw.clicked.connect(lambda _=False, c=color: self.set_color(hex_to_rgb(c), commit=True))
            swatches.addWidget(sw, 0, n)
        layout.addLayout(swatches)

        self.square.changed.connect(self._from_widgets)
        self.hue.changed.connect(self._from_widgets)
        self.square.mouseReleaseEvent = lambda _e: self.colorCommitted.emit(self.color())
        self.hue.mouseReleaseEvent = lambda _e: self.colorCommitted.emit(self.color())
        self.hex.editingFinished.connect(self._from_hex)
        self.set_color((255, 255, 255))

    def color(self) -> tuple[int, int, int]:
        c = QColor.fromHsvF(self.hue.hue, self.square.sat, self.square.val)
        return (c.red(), c.green(), c.blue())

    def set_color(self, rgb, commit: bool = False) -> None:
        c = QColor(*rgb)
        h, s, v, _ = c.getHsvF()
        self.hue.hue = max(0.0, h)
        self.square.hue, self.square.sat, self.square.val = self.hue.hue, s, v
        self.square.update()
        self.hue.update()
        self._refresh()
        self.colorChanged.emit(self.color())
        if commit:
            self.colorCommitted.emit(self.color())

    def _from_widgets(self) -> None:
        self.square.hue = self.hue.hue
        self.square.update()
        self._refresh()
        self.colorChanged.emit(self.color())

    def _from_hex(self) -> None:
        try:
            self.set_color(hex_to_rgb(self.hex.text()), commit=True)
        except ValueError:
            self._refresh()

    def _refresh(self) -> None:
        hex_color = rgb_to_hex(self.color())
        self.preview.setStyleSheet(f"background:{hex_color}; border:1px solid {theme.BORDER}; border-radius:8px;")
        if not self.hex.hasFocus():
            self.hex.setText(hex_color)


# ------------------------------------------------------------ keyboard view


class KeyboardView(QWidget):
    """Draws the keyboard from a profile; supports click, Shift-click and rubber-band selection."""

    selectionChanged = Signal()

    def __init__(self, profile, multi: bool = True) -> None:
        super().__init__()
        self.profile = profile
        self.multi = multi
        self.colors: dict[str, tuple[int, int, int]] = {}
        self.default_color: tuple[int, int, int] | None = None
        self.badges: dict[str, str] = {}
        self.disabled: set[str] = set()  # drawn faded; still selectable so the reason can be shown
        self.selected: set[str] = set()
        self.dim_unlit = False
        self._drag_start: QPointF | None = None
        self._drag_rect: QRectF | None = None
        self.cols = max((k.x + k.w for k in profile.keys), default=16)
        self.rows = max((k.row for k in profile.keys), default=5) + 1
        self.setMinimumSize(640, 230)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMouseTracking(True)

    def resizeEvent(self, event) -> None:
        wanted = self.heightForWidth(self.width())
        if abs(self.height() - wanted) > 2:
            self.setFixedHeight(wanted)
        super().resizeEvent(event)

    def heightForWidth(self, width: int) -> int:
        return int(width * (self.rows + 0.5) / (self.cols + 0.5))

    def hasHeightForWidth(self) -> bool:
        return True

    def _unit(self) -> float:
        return min((self.width() - 24) / self.cols, (self.height() - 24) / self.rows)

    def _key_rect(self, key) -> QRectF:
        u = self._unit()
        ox = (self.width() - self.cols * u) / 2
        oy = (self.height() - self.rows * u) / 2
        return QRectF(ox + key.x * u + 2, oy + key.row * u + 2, key.w * u - 4, u - 4)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        u = self._unit()
        plate = QRectF((self.width() - self.cols * u) / 2 - 10, (self.height() - self.rows * u) / 2 - 10,
                       self.cols * u + 20, self.rows * u + 20)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor("#0f1013"))
        p.drawRoundedRect(plate, 14, 14)

        label_font = QFont(self.font())
        label_font.setPointSizeF(max(6.5, u * 0.17))
        label_font.setBold(True)
        badge_font = QFont(self.font())
        badge_font.setPointSizeF(max(5.5, u * 0.13))
        for key in self.profile.keys:
            r = self._key_rect(key)
            rgb = self.colors.get(key.name, self.default_color)
            lit = rgb is not None and rgb != (0, 0, 0)
            base = QColor(*rgb) if rgb is not None else QColor("#23252b")
            # keycap body
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#191a1f"))
            p.drawRoundedRect(r, 7, 7)
            # light: colour glow on the cap
            if rgb is not None:
                glow = QColor(base)
                glow.setAlpha(235 if lit else 0)
                inner = r.adjusted(3, 3, -3, -5)
                p.setBrush(glow if lit else QColor("#16171b"))
                p.drawRoundedRect(inner, 5, 5)
            else:
                p.setBrush(QColor("#25272e"))
                p.drawRoundedRect(r.adjusted(3, 3, -3, -5), 5, 5)
            # outline
            selected = key.name in self.selected
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.ACCENT) if selected else QColor("#34373f"), 2.5 if selected else 1))
            p.drawRoundedRect(r, 7, 7)
            # legend
            text_color = readable_on(base) if lit else QColor("#c9ccd3")
            if key.name in self.disabled:
                text_color = QColor("#5a5e68")
            p.setPen(text_color)
            p.setFont(label_font)
            badge = self.badges.get(key.name)
            text_rect = r.adjusted(2, 0, -2, -(r.height() * 0.28 if badge else 0))
            p.drawText(text_rect, Qt.AlignCenter, _legend(key.name))
            if badge:
                badge_rect = QRectF(r.left() + 4, r.bottom() - r.height() * 0.36, r.width() - 8, r.height() * 0.28)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.ACCENT))
                p.drawRoundedRect(badge_rect, 4, 4)
                p.setPen(QColor("white"))
                p.setFont(badge_font)
                p.drawText(badge_rect, Qt.AlignCenter, p.fontMetrics().elidedText(badge, Qt.ElideRight,
                                                                                int(badge_rect.width())))
        if self._drag_rect is not None:
            p.setPen(QPen(QColor(theme.ACCENT), 1, Qt.DashLine))
            fill = QColor(theme.ACCENT)
            fill.setAlpha(40)
            p.setBrush(fill)
            p.drawRect(self._drag_rect)

    def key_at(self, pos) -> str | None:
        for key in self.profile.keys:
            if self._key_rect(key).contains(pos):
                return key.name
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is not None and self.multi:
            if (event.position() - self._drag_start).manhattanLength() > 6:
                self._drag_rect = QRectF(self._drag_start, event.position()).normalized()
                self.update()
        self.setCursor(Qt.PointingHandCursor if self.key_at(event.position()) else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_start is None:
            return
        shift = bool(event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)) and self.multi
        if self._drag_rect is not None:
            hit = {k.name for k in self.profile.keys if self._key_rect(k).intersects(self._drag_rect)}
            self.selected = (self.selected | hit) if shift else hit
        else:
            name = self.key_at(event.position())
            if name is None:
                if not shift:
                    self.selected = set()
            elif shift:
                self.selected ^= {name}
            else:
                self.selected = {name}
        self._drag_start = None
        self._drag_rect = None
        self.update()
        self.selectionChanged.emit()

    def set_selection(self, names) -> None:
        self.selected = set(names)
        self.update()
        self.selectionChanged.emit()


def _legend(name: str) -> str:
    return {"BACKSPACE": "Bksp", "BACKSLASH": "\\", "LBRACKET": "[", "RBRACKET": "]", "SEMICOLON": ";",
            "QUOTE": "'", "COMMA": ",", "DOT": ".", "SLASH": "/", "GRAVE": "`", "MINUS": "-", "EQUAL": "=",
            "SPACE": "", "LSHIFT": "Shift", "RSHIFT": "Shift", "LCTRL": "Ctrl", "LALT": "Alt", "RALT": "Alt",
            "LWIN": "Super", "PGUP": "PgUp", "PGDN": "PgDn", "ENTER": "Enter", "CAPS": "Caps", "TAB": "Tab",
            "LEFT": "←", "RIGHT": "→", "UP": "↑", "DOWN": "↓", "FN": "Fn", "ESC": "Esc",
            }.get(name, name)


# -------------------------------------------------------------- key capture

_QT_KEYS = {
    Qt.Key_Escape: "esc", Qt.Key_Tab: "tab", Qt.Key_Backtab: "tab", Qt.Key_Backspace: "backspace",
    Qt.Key_Return: "enter", Qt.Key_Enter: "kp_enter", Qt.Key_Space: "space", Qt.Key_Minus: "minus",
    Qt.Key_Equal: "equal", Qt.Key_BracketLeft: "lbracket", Qt.Key_BracketRight: "rbracket",
    Qt.Key_Backslash: "backslash", Qt.Key_Semicolon: "semicolon", Qt.Key_Apostrophe: "quote",
    Qt.Key_QuoteLeft: "grave", Qt.Key_Comma: "comma", Qt.Key_Period: "dot", Qt.Key_Slash: "slash",
    Qt.Key_CapsLock: "capslock", Qt.Key_Print: "printscreen", Qt.Key_ScrollLock: "scrolllock",
    Qt.Key_Pause: "pause", Qt.Key_Insert: "insert", Qt.Key_Home: "home", Qt.Key_PageUp: "pageup",
    Qt.Key_Delete: "delete", Qt.Key_End: "end", Qt.Key_PageDown: "pagedown", Qt.Key_Right: "right",
    Qt.Key_Left: "left", Qt.Key_Down: "down", Qt.Key_Up: "up", Qt.Key_NumLock: "numlock",
    Qt.Key_Menu: "menu", Qt.Key_VolumeUp: "volup", Qt.Key_VolumeDown: "voldown", Qt.Key_VolumeMute: "mute",
    Qt.Key_MediaPlay: "playpause", Qt.Key_MediaTogglePlayPause: "playpause", Qt.Key_MediaNext: "next",
    Qt.Key_MediaPrevious: "prev", Qt.Key_MediaStop: "stop",
}
for _i in range(26):
    _QT_KEYS[Qt.Key(Qt.Key_A.value + _i)] = chr(ord("a") + _i)
for _i in range(10):
    _QT_KEYS[Qt.Key(Qt.Key_0.value + _i)] = str(_i)
for _i in range(24):
    _QT_KEYS[Qt.Key(Qt.Key_F1.value + _i)] = f"f{_i + 1}"
# X11/evdev scan codes distinguish left and right modifiers
_MOD_SCANCODES = {37: "lctrl", 105: "rctrl", 50: "lshift", 62: "rshift", 64: "lalt", 108: "ralt",
                  133: "lgui", 134: "rgui"}
_MOD_KEYS = {Qt.Key_Control: "lctrl", Qt.Key_Shift: "lshift", Qt.Key_Alt: "lalt", Qt.Key_Meta: "lgui",
             Qt.Key_Super_L: "lgui", Qt.Key_Super_R: "rgui", Qt.Key_AltGr: "ralt"}


# Linux evdev codes (X11/Wayland native scan code minus 8) to HID names: the
# physical key, independent of the keyboard layout and of Shift.
_EVDEV = {1: "esc", 12: "minus", 13: "equal", 14: "backspace", 15: "tab", 26: "lbracket", 27: "rbracket",
          28: "enter", 39: "semicolon", 40: "quote", 41: "grave", 43: "backslash", 51: "comma", 52: "dot",
          53: "slash", 57: "space", 58: "capslock", 87: "f11", 88: "f12", 102: "home", 103: "up",
          104: "pageup", 105: "left", 106: "right", 107: "end", 108: "down", 109: "pagedown", 110: "insert",
          111: "delete", 99: "printscreen", 119: "pause", 70: "scrolllock", 127: "menu", 113: "mute",
          114: "voldown", 115: "volup", 164: "playpause", 163: "next", 165: "prev", 166: "stop"}
_EVDEV.update({2 + i: str((i + 1) % 10) for i in range(10)})
_EVDEV.update({59 + i: f"f{i + 1}" for i in range(10)})
_EVDEV.update({183 + i: f"f{i + 13}" for i in range(12)})
_EVDEV.update(dict(zip(range(16, 26), "qwertyuiop")))
_EVDEV.update(dict(zip(range(30, 39), "asdfghjkl")))
_EVDEV.update(dict(zip(range(44, 51), "zxcvbnm")))


def target_from_event(event: QKeyEvent) -> str | None:
    """Translate a key press into a remap target such as "ctrl+c" or "f13"."""
    key = Qt.Key(event.key())
    if key in _MOD_KEYS:
        return _MOD_SCANCODES.get(event.nativeScanCode(), _MOD_KEYS[key])
    name = _EVDEV.get(event.nativeScanCode() - 8) or _QT_KEYS.get(key)
    if name is None:
        return None
    mods = []
    m = event.modifiers()
    if m & Qt.ControlModifier:
        mods.append("ctrl")
    if m & Qt.ShiftModifier:
        mods.append("shift")
    if m & Qt.AltModifier:
        mods.append("alt")
    if m & Qt.MetaModifier:
        mods.append("win")
    return "+".join([*mods, name])


class KeyCapture(QPushButton):
    """Click, then press a key or combination; emits the remap target."""

    captured = Signal(str)

    def __init__(self) -> None:
        super().__init__("Press to record a key")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(44)
        self.toggled.connect(self._toggled)

    def _toggled(self, on: bool) -> None:
        if on:
            self.setText("Press a key or combination... (Esc twice to cancel)")
            self.setFocus()
            self.grabKeyboard()
            self._escapes = 0
        else:
            self.releaseKeyboard()
            self.setText("Press to record a key")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self.isChecked():
            return super().keyPressEvent(event)
        if event.isAutoRepeat():
            return
        key = Qt.Key(event.key())
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return  # wait for the key that completes the combination; release records a lone modifier
        if key == Qt.Key_Escape:
            self._escapes += 1
            if self._escapes >= 2:
                self.setChecked(False)
                return
            self._pending_escape = True
            QTimer.singleShot(600, self._commit_escape)
            return
        target = target_from_event(event)
        if target:
            self.setChecked(False)
            self.captured.emit(target)

    def _commit_escape(self) -> None:
        if self.isChecked() and self._escapes == 1:
            self.setChecked(False)
            self.captured.emit("esc")

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if self.isChecked() and Qt.Key(event.key()) in _MOD_KEYS:
            target = target_from_event(event)
            self.setChecked(False)
            if target:
                self.captured.emit(target)
            return
        super().keyReleaseEvent(event)


def key_name_from_event(event: QKeyEvent) -> str | None:
    """The single physical key of an event (modifiers as lctrl, rshift, ...), without held modifiers."""
    key = Qt.Key(event.key())
    if key in _MOD_KEYS:
        return _MOD_SCANCODES.get(event.nativeScanCode(), _MOD_KEYS[key])
    return _EVDEV.get(event.nativeScanCode() - 8) or _QT_KEYS.get(key)


class MacroRecorder(QPushButton):
    """Click to start, type the sequence, click again to stop. Emits macro tokens with the real timing."""

    recorded = Signal(str)

    def __init__(self) -> None:
        super().__init__("Record")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.with_delays = True
        self.tokens: list[str] = []
        self._last = 0.0
        self.toggled.connect(self._toggled)

    def _toggled(self, on: bool) -> None:
        import time

        if on:
            self.tokens = []
            self._last = time.monotonic()
            self.setText("Recording... click to stop")
            self.setFocus()
            self.grabKeyboard()
        else:
            self.releaseKeyboard()
            self.setText("Record")
            if self.tokens:
                self.recorded.emit(" ".join(self.tokens))

    def _add(self, token: str) -> None:
        import time

        now = time.monotonic()
        gap = int((now - self._last) * 1000)
        if self.with_delays and self.tokens and gap > 10:
            self.tokens.append(f"{min(gap, 65535)}ms")
        self.tokens.append(token)
        self._last = now

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self.isChecked():
            return super().keyPressEvent(event)
        name = key_name_from_event(event)
        if name and not event.isAutoRepeat():
            self._add(f"+{name}")

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if not self.isChecked():
            return super().keyReleaseEvent(event)
        name = key_name_from_event(event)
        if name and not event.isAutoRepeat():
            self._add(f"-{name}")


def compact_tokens(text: str) -> str:
    """Turn '+a -a' pairs without a delay between them into 'a' for readability."""
    tokens = text.split()
    out: list[str] = []
    for token in tokens:
        if token.startswith("-") and out and out[-1] == "+" + token[1:]:
            out[-1] = token[1:]
        else:
            out.append(token)
    return " ".join(out)


# -------------------------------------------------------------------- toast


class Toast(QLabel):
    """Short notification in the bottom-right corner of its parent."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def reposition(self) -> None:
        parent = self.parentWidget()
        self.move(parent.width() - self.width() - 28, 18)

    def show_message(self, text: str, kind: str = "ok", timeout_ms: int = 2600) -> None:
        self.setText(text)
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        self.adjustSize()
        self.reposition()
        self.raise_()
        self.show()
        if timeout_ms:
            self._timer.start(timeout_ms)
        else:
            self._timer.stop()
