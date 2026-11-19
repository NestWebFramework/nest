"""Telling a photo's words from what a camera or an upload left in their place.

WordPress's gallery plugins fill a photo's alt text with its file name
("morlaca035 20121226 1435168974") and its description with the camera's data
("Aperture: 7.1 Camera: NIKON D40 Iso: 200"). Neither tells a reader, or a search
engine, what the photo shows, so neither is shown as such: ``alt()`` and ``caption()``
give the photo's real words or nothing.
"""

from __future__ import annotations

import re

_NAME = re.compile(r"^[\w.\- ]+$")
_CAMERA = {
    "aperture",
    "camera",
    "iso",
    "focal length",
    "shutter speed",
    "orientation",
    "credit",
    "copyright",
    "created timestamp",
    "exposure",
    "flash",
    "make",
    "model",
    "lens",
    "title",
}
_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z ]{1,24})\s*:\s*\S")


def is_file_name(text: str) -> bool:
    """A name a file was given, not words: mostly digits, or ending like one."""
    text = (text or "").strip()
    if not text or not _NAME.match(text):
        return False
    digits = sum(ch.isdigit() for ch in text)
    if digits >= max(6, len(text) // 3):
        return True
    return bool(re.search(r"\.(jpe?g|png|gif|webp)$", text, re.I)) or bool(
        re.match(r"^(img|dsc|dscn|p\d|photo)[_\- ]?\d+", text, re.I)
    )


def is_camera_data(text: str) -> bool:
    """A camera's record (Aperture: 7.1, Camera: NIKON D40...), not a caption."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return False
    known = 0
    for line in lines:
        m = _LINE.match(line)
        if not m:
            return False
        known += m.group(1).strip().lower() in _CAMERA
    return known >= max(1, len(lines) // 2)


def is_label(text: str) -> bool:
    """A labelled line (Author: ..., Foto: ...): worth keeping, but it says who, not what."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return bool(lines) and all(_LINE.match(line) for line in lines)


def describes(text: str) -> str:
    """A caption's words when they say what the photo shows (not a credit, not a camera)."""
    said = caption(text)
    return "" if is_label(said) else said


def alt(text: str) -> str:
    text = " ".join((text or "").split())
    return "" if is_file_name(text) else text


def caption(text: str) -> str:
    text = (text or "").strip()
    return "" if is_camera_data(text) else text
