"""Image conversion for the keyboard screen."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def rgb565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def encode(image: Image.Image, width: int, height: int, transpose: bool = True) -> bytes:
    """Fit *image* to width x height and return big-endian RGB565 bytes.

    With *transpose* the pixels are emitted column by column, which is the
    order the RT100 firmware expects.
    """
    frame = ImageOps.fit(image.convert("RGB"), (width, height), Image.Resampling.LANCZOS)
    if transpose:
        frame = frame.transpose(Image.Transpose.TRANSPOSE)
    raw = frame.tobytes()
    out = bytearray()
    for i in range(0, len(raw), 3):
        out += rgb565(raw[i], raw[i + 1], raw[i + 2]).to_bytes(2, "big")
    return bytes(out)


def encode_file(path: str | Path, width: int, height: int, transpose: bool = True) -> bytes:
    with Image.open(path) as image:
        image.seek(0)  # first frame of animated formats
        return encode(image, width, height, transpose)
