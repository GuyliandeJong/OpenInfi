"""Image conversion for the keyboard screen."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def rgb565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def encode(image: Image.Image, width: int, height: int, transpose: bool = True,
           byteorder: str = "big", fit: str = "crop") -> bytes:
    """Scale *image* to width x height and return RGB565 bytes.

    *fit* is "crop" (fill, cropping the overflow), "stretch" (what the
    INFI75 vendor driver does) or "pad" (letterbox on black). With
    *transpose* the pixels are emitted column by column, which is the
    order the RT100 firmware expects.
    """
    source = image.convert("RGB")
    size = (width, height)
    if fit == "stretch":
        frame = source.resize(size, Image.Resampling.LANCZOS)
    elif fit == "pad":
        frame = ImageOps.pad(source, size, Image.Resampling.LANCZOS, color=(0, 0, 0))
    else:
        frame = ImageOps.fit(source, size, Image.Resampling.LANCZOS)
    if transpose:
        frame = frame.transpose(Image.Transpose.TRANSPOSE)
    raw = frame.tobytes()
    out = bytearray()
    for i in range(0, len(raw), 3):
        out += rgb565(raw[i], raw[i + 1], raw[i + 2]).to_bytes(2, byteorder)
    return bytes(out)


def encode_file(path: str | Path, width: int, height: int, transpose: bool = True) -> bytes:
    with Image.open(path) as image:
        image.seek(0)  # first frame of animated formats
        return encode(image, width, height, transpose)


def frames_from_file(path: str | Path, width: int, height: int, max_frames: int, fit: str = "crop",
                     byteorder: str = "little") -> list[tuple[bytes, int]]:
    """All frames of a still or animated image as (RGB565, duration ms)."""
    frames = []
    with Image.open(path) as image:
        count = getattr(image, "n_frames", 1)
        for n in range(min(count, max_frames)):
            image.seek(n)
            duration = int(image.info.get("duration", 100) or 100)
            frames.append((encode(image, width, height, False, byteorder, fit), duration))
    return frames
