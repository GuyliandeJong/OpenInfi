"""USB HID keyboard usage codes (HID Usage Tables, page 0x07) and media keys.

Used as the *target* of a key remap: the keyboard sends this code when the
remapped physical key is pressed.
"""

from __future__ import annotations

_CODES: dict[str, int] = {}

for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _CODES[_c] = 0x04 + _i
for _i, _c in enumerate("1234567890"):
    _CODES[_c] = 0x1E + _i
for _i in range(12):
    _CODES[f"f{_i + 1}"] = 0x3A + _i
for _i in range(12):
    _CODES[f"f{_i + 13}"] = 0x68 + _i
for _i in range(9):
    _CODES[f"kp{_i + 1}"] = 0x59 + _i

_CODES.update(
    {
        "none": 0x00,
        "enter": 0x28,
        "esc": 0x29,
        "backspace": 0x2A,
        "tab": 0x2B,
        "space": 0x2C,
        "minus": 0x2D,
        "equal": 0x2E,
        "lbracket": 0x2F,
        "rbracket": 0x30,
        "backslash": 0x31,
        "nonus_hash": 0x32,
        "semicolon": 0x33,
        "quote": 0x34,
        "grave": 0x35,
        "comma": 0x36,
        "dot": 0x37,
        "slash": 0x38,
        "capslock": 0x39,
        "printscreen": 0x46,
        "scrolllock": 0x47,
        "pause": 0x48,
        "insert": 0x49,
        "home": 0x4A,
        "pageup": 0x4B,
        "delete": 0x4C,
        "end": 0x4D,
        "pagedown": 0x4E,
        "right": 0x4F,
        "left": 0x50,
        "down": 0x51,
        "up": 0x52,
        "numlock": 0x53,
        "kp_slash": 0x54,
        "kp_asterisk": 0x55,
        "kp_minus": 0x56,
        "kp_plus": 0x57,
        "kp_enter": 0x58,
        "kp0": 0x62,
        "kp_dot": 0x63,
        "nonus_backslash": 0x64,
        "menu": 0x65,
        "mute": 0x7F,
        "volup": 0x80,
        "voldown": 0x81,
        "lctrl": 0xE0,
        "lshift": 0xE1,
        "lalt": 0xE2,
        "lgui": 0xE3,
        "rctrl": 0xE4,
        "rshift": 0xE5,
        "ralt": 0xE6,
        "rgui": 0xE7,
    }
)

_ALIASES = {
    "escape": "esc",
    "return": "enter",
    "bksp": "backspace",
    "del": "delete",
    "ins": "insert",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "caps": "capslock",
    "win": "lgui",
    "lwin": "lgui",
    "rwin": "rgui",
    "cmd": "lgui",
    "ctrl": "lctrl",
    "shift": "lshift",
    "alt": "lalt",
    "`": "grave",
    "-": "minus",
    "=": "equal",
    "[": "lbracket",
    "]": "rbracket",
    "\\": "backslash",
    ";": "semicolon",
    "'": "quote",
    ",": "comma",
    ".": "dot",
    "/": "slash",
}


def names() -> list[str]:
    """All canonical key names, sorted by HID code."""
    return sorted(_CODES, key=lambda n: (_CODES[n], n))


def code(name: str) -> int:
    """Resolve a key name, alias or numeric literal (``0x2c``, ``44``) to a HID code."""
    key = name.strip().lower()
    key = _ALIASES.get(key, key)
    if key in _CODES:
        return _CODES[key]
    try:
        value = int(key, 0)
    except ValueError:
        raise KeyError(f"unknown key name {name!r}; run 'infi75 keys --hid' for the list") from None
    if not 0 <= value <= 0xFF:
        raise KeyError(f"HID code out of range: {name!r}")
    return value


def name(hid_code: int) -> str:
    """Reverse lookup; returns a hex literal for codes without a name."""
    for key, value in _CODES.items():
        if value == hid_code:
            return key
    return f"0x{hid_code:02x}"
