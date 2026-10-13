"""Image conversion for the keyboard screen."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def rgb565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def fit_frame(image: Image.Image, width: int, height: int, fit: str = "crop") -> Image.Image:
    """Scale to width x height: "crop" fills and crops, "stretch" distorts, "pad" letterboxes."""
    source = image.convert("RGB")
    size = (width, height)
    if fit == "stretch":
        return source.resize(size, Image.Resampling.LANCZOS)
    if fit == "pad":
        return ImageOps.pad(source, size, Image.Resampling.LANCZOS, color=(0, 0, 0))
    return ImageOps.fit(source, size, Image.Resampling.LANCZOS)


def preview_frames(path: str | Path, width: int, height: int, max_frames: int,
                   fit: str = "crop") -> list[tuple[Image.Image, int]]:
    """Fitted RGB frames and durations, as they will appear on the screen."""
    frames = []
    with Image.open(path) as image:
        for n in range(min(getattr(image, "n_frames", 1), max_frames)):
            image.seek(n)
            frames.append((fit_frame(image, width, height, fit), int(image.info.get("duration", 100) or 100)))
    return frames


def encode(image: Image.Image, width: int, height: int, byteorder: str = "little", fit: str = "crop") -> bytes:
    """Scale *image* to width x height and return RGB565 bytes, row by row from the top left.

    *fit* is "crop" (fill, cropping the overflow), "stretch" (what the
    INFI75 vendor driver does) or "pad" (letterbox on black).
    """
    frame = fit_frame(image, width, height, fit)
    raw = frame.tobytes()
    out = bytearray()
    for i in range(0, len(raw), 3):
        out += rgb565(raw[i], raw[i + 1], raw[i + 2]).to_bytes(2, byteorder)
    return bytes(out)


def frames_from_file(path: str | Path, width: int, height: int, max_frames: int, fit: str = "crop",
                     byteorder: str = "little") -> list[tuple[bytes, int]]:
    """All frames of a still or animated image as (RGB565, duration ms)."""
    frames = []
    with Image.open(path) as image:
        count = getattr(image, "n_frames", 1)
        for n in range(min(count, max_frames)):
            image.seek(n)
            duration = int(image.info.get("duration", 100) or 100)
            frames.append((encode(image, width, height, byteorder, fit), duration))
    return frames
