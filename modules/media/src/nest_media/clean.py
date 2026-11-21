"""An uploaded picture made safe to keep: read whole, checked, its metadata dropped.

``clean(data)`` reads the picture with Pillow (all of it, not only its first bytes), so a
file that only starts like a picture, a "polyglot" with something else after its header,
or a broken one, is refused; so is one larger than MAX_PIXELS (a decompression bomb,
small on disk, enormous once decoded). It is then written again: turned upright as its
camera said (EXIF orientation), and without its metadata, the EXIF and XMP a phone puts
in (the place it was taken, to the metre; the camera; the time). Its colour profile is
kept, so its colours stay right. JPEG is written at quality 90, PNG and lossless WebP
losslessly; an animated GIF or WebP keeps its frames.
"""

from __future__ import annotations

import io
from typing import Any

MAX_PIXELS = 50_000_000  # as for the sized copies: past this, a picture is refused
TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}


class ImageError(ValueError):
    """Why a picture is refused: a message to translate, with its params."""

    def __init__(self, message: str, **params: Any):
        self.message, self.params = message, params
        super().__init__(message.format(**params) if params else message)


def sniff(head: bytes) -> str | None:
    """A picture's type from its first bytes (what it says it is, before it is read)."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def clean(data: bytes, *, max_pixels: int = MAX_PIXELS) -> tuple[bytes, str]:
    """The picture written again without its metadata, and its type; ImageError if it is
    not one of JPEG, PNG, WebP or GIF that can be read whole, or is too large."""
    from PIL import Image, ImageOps  # noqa: PLC0415 - only an upload needs it

    if sniff(data[:16]) is None:
        raise ImageError("Only JPEG, PNG, WebP and GIF pictures.")
    try:
        with Image.open(io.BytesIO(data)) as probe:  # its size is read before its pixels
            if probe.format not in TYPES:
                raise ImageError("Only JPEG, PNG, WebP and GIF pictures.")
            if probe.width * probe.height > max_pixels:
                raise ImageError(
                    "The picture is too large ({w}×{h} pixels).", w=probe.width, h=probe.height
                )
            probe.verify()  # its structure, whole
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            icc = img.info.get("icc_profile")
            out = io.BytesIO()
            if getattr(img, "is_animated", False) and fmt in ("GIF", "WEBP"):
                frames = []
                for i in range(img.n_frames):
                    img.seek(i)
                    frames.append(img.copy())
                extra: dict[str, Any] = {"loop": img.info.get("loop", 0)}
                if "duration" in img.info:
                    extra["duration"] = img.info["duration"]
                if fmt == "WEBP":
                    extra.update(lossless=bool(img.info.get("lossless")), quality=90)
                frames[0].save(out, fmt, save_all=True, append_images=frames[1:], **extra)
            else:
                img.load()
                pic = ImageOps.exif_transpose(
                    img
                )  # upright; the orientation tag goes with the rest
                kept = {"icc_profile": icc} if icc else {}
                if fmt == "JPEG":
                    if pic.mode not in ("RGB", "L", "CMYK"):
                        pic = pic.convert("RGB")
                    pic.save(out, "JPEG", quality=90, optimize=True, progressive=True, **kept)
                elif fmt == "PNG":
                    pic.save(out, "PNG", optimize=True, **kept)
                elif fmt == "WEBP":
                    lossless = bool(img.info.get("lossless"))
                    pic.save(out, "WEBP", lossless=lossless, quality=90, method=4, **kept)
                else:  # a still GIF
                    pic.save(out, "GIF")
    except ImageError:
        raise
    except (OSError, SyntaxError, ValueError, EOFError, Image.DecompressionBombError) as e:
        raise ImageError(
            "The picture cannot be read: it is damaged, or not what it claims to be."
        ) from e
    return out.getvalue(), TYPES[fmt]
