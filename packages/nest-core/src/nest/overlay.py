"""Module versions chosen on a running site, kept in its workspace: the overlay.

A site's packages come with its image (or its checkout's environment), which the site
cannot change: in a container that code is read only and made again at every restart.
What an administrator chooses in the admin panel (Modules: update, another version, a
module added from the registry) is kept in the workspace instead, which lasts:

    <workspace>/packages/pins.json            what was chosen, by distribution
    <workspace>/packages/<dist>-<version>/    each chosen version, unpacked from its wheel

Each pin remembers the version the image had when it was chosen (``base``). A site may
be deployed with another image later, whose packages are other versions, so every start
decides again (``check``): a pin over an image that did not move is used; over an image
that brought a newer (or the same) version, the image wins and the pin is set aside;
over one that brought an older version, the pin is kept, since its tables may be
migrated past what the image's knows; and a pin that no longer fits the image's other
packages (what it needs, what they need of it) is set aside, saying why (the panel shows
it). So a redeploy is never undone by an older choice, nor broken by a newer one.

A process loads the overlay once, before any module is imported. A change is applied
by new processes (nest serve's workers reloaded, the engine restarted); the old code is
taken out of the master first (``activate(purge=True)``), so the workers it forks import
the chosen versions.
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

log = logging.getLogger("nest.overlay")

FOLDER = "packages"
PINS = "pins.json"

_loaded: dict[str, set[str]] = {}  # by workspace: the folders this process put on sys.path


@dataclass
class Pin:
    dist: str  # the distribution (nest-forum)
    version: str  # the version chosen
    name: str = ""  # the package's name in Nest (forum)
    base: str | None = None  # the image's version when it was chosen (None: not in the image)
    at: str = ""
    who: str = ""

    def folder(self, workspace: Path) -> Path:
        return folder(workspace) / f"{_norm(self.dist)}-{self.version}"


def _norm(dist: str) -> str:
    return dist.lower().replace("_", "-")


def folder(workspace: Path) -> Path:
    return Path(workspace) / FOLDER


def load_pins(workspace: Path) -> dict[str, Pin]:
    path = folder(workspace) / PINS
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        log.error("%s is not JSON: the image's packages are used", path)
        return {}
    return {_norm(k): Pin(**{**v, "dist": _norm(k)}) for k, v in (raw or {}).items()}


def save_pins(workspace: Path, pins: dict[str, Pin]) -> None:
    base = folder(workspace)
    base.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {d: {k: v for k, v in asdict(p).items() if k != "dist"} for d, p in sorted(pins.items())},
        indent=1,
        ensure_ascii=False,
    )
    tmp = base / (PINS + ".tmp")
    tmp.write_text(body + "\n", encoding="utf-8")
    tmp.replace(base / PINS)


def _outside(workspace: Path) -> list[str]:
    """sys.path without any overlay folder (what the image itself has)."""
    mine = str(folder(workspace).resolve())
    return [p for p in sys.path if not str(Path(p or ".").resolve()).startswith(mine)]


def image_version(dist: str, workspace: Path) -> str | None:
    """The version the image (the environment, overlay aside) has of ``dist``."""
    for d in metadata.distributions(path=_outside(workspace)):
        if _norm(d.metadata["Name"] or "") == _norm(dist):
            return d.version
    return None


def _vkey(v: str | None) -> Any:
    from packaging.version import InvalidVersion, Version  # noqa: PLC0415

    try:
        return Version(v or "0")
    except InvalidVersion:
        return Version("0")


def _requires(folder: Path) -> list[str]:
    """What a pinned version requires (its wheel's Requires-Dist)."""
    from email.parser import Parser  # noqa: PLC0415

    meta = next(folder.glob("*.dist-info/METADATA"), None)
    if meta is None:
        return []
    return Parser().parsestr(meta.read_text(encoding="utf-8")).get_all("Requires-Dist") or []


def _image_requirements(workspace: Path) -> list[tuple[str, str, str]]:
    """Every requirement the image's own packages have: (who, the dist it needs, the
    requirement), so a pin they would not take is found."""
    out = []
    for d in metadata.distributions(path=_outside(workspace)):
        who = _norm(d.metadata["Name"] or "")
        for line in d.requires or []:
            from packaging.requirements import InvalidRequirement, Requirement  # noqa: PLC0415

            try:
                req = Requirement(line)
            except InvalidRequirement:
                continue
            if req.marker is not None and not req.marker.evaluate({"extra": ""}):
                continue
            out.append((who, _norm(req.name), line))
    return out


def check(workspace: Path) -> tuple[dict[str, Pin], dict[str, tuple[Pin, str]], bool]:
    """Which pins the site uses with the image it runs now, and why the others are set
    aside; whether pins.json was brought up to date. An image deployed since a choice may
    carry other versions of everything, so each start decides again:

    * the image has the version the pin was chosen over (``base``): the pin is used;
    * the image moved, to a version **older** than the pin: the pin is kept (its tables
      may be migrated past what the image's version knows; the newer code is the one that
      matches them), ``base`` brought up to the image's;
    * the image moved to the pin's version or a newer one: the image wins, the pin is set
      aside (its tables migrate up at start, as an upgrade's do);
    * a pin used must fit: what it requires is there (the image's packages, other pins),
      and what the image's packages require of it holds; one that does not is set aside
      too, until nothing changes.
    """
    from packaging.requirements import InvalidRequirement, Requirement  # noqa: PLC0415

    pins = load_pins(workspace)
    used: dict[str, Pin] = {}
    aside: dict[str, tuple[Pin, str]] = {}
    rebased = False
    for dist, pin in pins.items():
        image = image_version(dist, workspace)
        if not pin.folder(workspace).is_dir():
            aside[dist] = (pin, "its files are missing")
        elif image == pin.base:
            used[dist] = pin
        elif image is not None and _vkey(pin.version) > _vkey(image):
            pin.base, rebased = image, True  # kept: newer than what the image brings now
            used[dist] = pin
        else:
            aside[dist] = (pin, f"the image has {image or 'none'} now")
    image_reqs = _image_requirements(workspace)
    changed = True
    while changed:
        changed = False
        have = {
            _norm(d.metadata["Name"] or ""): d.version
            for d in metadata.distributions(path=_outside(workspace))
        }
        have.update({d: p.version for d, p in used.items()})
        for dist, pin in list(used.items()):
            why = None
            for line in _requires(pin.folder(workspace)):
                try:
                    req = Requirement(line)
                except InvalidRequirement:
                    continue
                if req.marker is not None and not req.marker.evaluate({"extra": ""}):
                    continue
                got = have.get(_norm(req.name))
                if got is None or (
                    req.specifier and not req.specifier.contains(got, prereleases=True)
                ):
                    why = f"it needs {line}; the site has {got or 'none'}"
                    break
            if why is None:
                for who, needed, line in image_reqs:
                    if needed != dist or who in used:
                        continue
                    spec = Requirement(line).specifier
                    if spec and not spec.contains(pin.version, prereleases=True):
                        why = f"the image's {who} needs {line}"
                        break
            if why is not None:
                aside[dist] = (used.pop(dist), why)
                changed = True
    if rebased:
        save_pins(workspace, {**{d: p for d, (p, _w) in aside.items()}, **used})
    return used, aside, rebased


def active(workspace: Path) -> tuple[dict[str, Pin], dict[str, Pin]]:
    """(the pins in use, the pins set aside: see ``check``)."""
    used, aside, _rebased = check(workspace)
    return used, {d: p for d, (p, _why) in aside.items()}


def top_levels(dist_folder: Path) -> set[str]:
    """The importable names a pinned version brings (from its wheel's RECORD)."""
    names: set[str] = set()
    for info in dist_folder.glob("*.dist-info"):
        record = info / "RECORD"
        if not record.is_file():
            continue
        for line in record.read_text(encoding="utf-8").splitlines():
            first = line.split(",", 1)[0].split("/", 1)[0]
            if first and not first.endswith((".dist-info", ".data")) and first != "..":
                names.add(first.removesuffix(".py"))
    return names


def activate(workspace: Path, *, purge: bool = False) -> list[str]:
    """Put the pins in use on sys.path, ahead of the image's packages: once a process
    (later calls change nothing: a running process never mixes versions), unless
    ``purge``, which also drops the code imported from what changed, for the processes
    made next (nest serve's master before it forks, nest run before it remakes the
    application). The pins in use, as dist==version."""
    key = str(Path(workspace).resolve())
    if key in _loaded and not purge:
        return []
    used, aside_why, _rebased = check(workspace)
    for dist, (pin, why) in aside_why.items():
        log.warning("the version chosen of %s (%s) is set aside: %s", dist, pin.version, why)
    wanted = [str(p.folder(workspace)) for p in used.values()]
    before = _loaded.get(key, set())
    changed = before.symmetric_difference(wanted)
    for path in before - set(wanted):
        while path in sys.path:
            sys.path.remove(path)
    for path in wanted:
        if path not in sys.path:
            sys.path.insert(0, path)
    if purge and changed:
        names: set[str] = set()
        for path in changed:
            names |= top_levels(Path(path))
        for mod in list(sys.modules):
            if mod.split(".", 1)[0] in names:
                del sys.modules[mod]
        log.info("code of %s taken out, for the processes made next", ", ".join(sorted(names)))
    importlib.invalidate_caches()
    _loaded[key] = set(wanted)
    return [f"{p.dist}=={p.version}" for p in used.values()]


def describe(workspace: Path) -> dict[str, Any]:
    """What the panel shows: the pins in use and those set aside, with the image's version."""
    used, aside, _rebased = check(workspace)
    return {
        "used": {d: {**asdict(p), "image": image_version(d, workspace)} for d, p in used.items()},
        "aside": {
            d: {**asdict(p), "image": image_version(d, workspace), "why": why}
            for d, (p, why) in aside.items()
        },
    }
