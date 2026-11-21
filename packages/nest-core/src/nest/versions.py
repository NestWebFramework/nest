"""Module versions on a running site: updates, another version, back to the image's, a
module added from the registry; and its migrations, up and down.

The versions chosen are kept in the workspace (nest.overlay). A change is one step, done
in a process of its own (``nest modules <app> version …``, which the admin panel runs),
never in the running site:

1. each version asked is found in the Nest registry (it must work with this nest-core,
   and not be yanked), its wheel downloaded and checked: its sha256 as the registry says,
   its signature when the package is pinned to keys (``nest trust``);
2. what each needs must be there after the change: a Nest package at a version its
   range takes (asked in the same change, chosen before, or the image's), anything else
   in the image already (a site cannot install what is not Nest's);
3. the workspace is backed up;
4. a module taken to an older version has its migrations taken down first, with the
   code it has now, to the newest revision the older version knows;
5. the pins are written, and the application is made in a new process with them, which
   migrates up what moved up (NEST_MIGRATE=auto) and proves the site starts;
6. if anything fails, the pins go back and the application is made again with them (its
   migrations up again where they were taken down); the backup stays, for the worst case;
7. the running site is then reloaded by the caller (nest serve's workers, the engine).

Every change, done or refused, is written in the workspace's modules log.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.parser import Parser
from importlib import metadata
from pathlib import Path
from typing import Any

from nest import overlay
from nest.manifest import MANIFEST_FILE, load_manifest
from nest.workspace import resolve_workspace

IMAGE = "image"  # asked for a module: back to the image's version (its pin dropped)
CORE = "nest-core"  # never changed here: it is the image's, as Python is


class VersionError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass
class Installed:
    """A Nest package of the site, as the panel shows it."""

    name: str
    dist: str
    type: str
    title: str
    running: str  # the version this process loaded
    image: str | None  # the image's version
    pinned: str | None  # the version chosen in the panel (in use)
    aside: str | None = None  # a version chosen before, set aside (the image changed since)
    aside_why: str = ""  # why it is set aside
    latest: str | None = None  # the registry's newest that works with this nest-core
    versions: list[str] = field(default_factory=list)  # every release that works with it
    migrations: dict[str, Any] | None = None  # {"current": [...], "head": [...]} when it has


@dataclass
class Staged:
    name: str
    dist: str
    version: str
    folder: Path
    requires: list[str]
    current: str | None  # the version running before


def _core() -> str | None:
    try:
        return metadata.version(CORE)
    except metadata.PackageNotFoundError:
        return None


def _norm(dist: str) -> str:
    return dist.lower().replace("_", "-")


def _vkey(v: str) -> Any:
    from packaging.version import InvalidVersion, Version  # noqa: PLC0415

    try:
        return Version(v)
    except InvalidVersion:
        return Version("0")


def dist_of(entry: Any) -> str | None:
    """The distribution a catalog entry comes from (nest-forum)."""
    if entry is None or not entry.package:
        return None
    top = entry.package.split(".")[0]
    for ep in metadata.entry_points(group="nest.modules"):  # editable installs too
        if ep.value.split(":")[0].split(".")[0] == top and ep.dist is not None:
            return _norm(ep.dist.metadata["Name"] or ep.dist.name)
    found = metadata.packages_distributions().get(top)
    return _norm(found[0]) if found else None


# --- reading -----------------------------------------------------------------------------


def installed(
    app_dir: str | Path,
    environ: Mapping[str, str] | None = None,
    *,
    offers: dict[str, dict[str, Any]] | None = None,
) -> list[Installed]:
    """The site's Nest packages (what came installed from a package, not its own folder's
    modules), with their versions: running, the image's, chosen, the registry's newest
    (from ``offers``: the registry's catalog by name, when given)."""
    from nest.catalog import Catalog  # noqa: PLC0415

    app_dir = Path(app_dir).resolve()
    environ = dict(os.environ if environ is None else environ)
    workspace = resolve_workspace(load_manifest(app_dir).name, environ)
    overlay.activate(workspace)
    used, aside_why, _rebased = overlay.check(workspace)
    aside = {d: p for d, (p, _w) in aside_why.items()}
    out = []
    for entry in Catalog.discover(app_dir):
        dist = dist_of(entry)
        if dist is None or dist == CORE:
            continue
        m = entry.manifest
        offer = (offers or {}).get(entry.name) or {}
        out.append(
            Installed(
                name=entry.name,
                dist=dist,
                type=entry.type,
                title=m.module.title or entry.name,
                running=m.module.version,
                image=overlay.image_version(dist, workspace),
                pinned=used[dist].version if dist in used else None,
                aside=aside[dist].version if dist in aside else None,
                aside_why=aside_why[dist][1] if dist in aside_why else "",
                latest=offer.get("version"),
                versions=list(offer.get("versions") or []),
            )
        )
    return sorted(out, key=lambda i: (i.type, i.name))


def updates(rows: list[Installed]) -> list[Installed]:
    """The packages whose registry has a newer version than the one running."""
    return [r for r in rows if r.latest and _vkey(r.latest) > _vkey(r.running)]


# --- fetching and checking a version --------------------------------------------------------


def _release(detail: dict[str, Any], version: str, core: str | None) -> dict[str, Any]:
    from packaging.specifiers import SpecifierSet  # noqa: PLC0415

    name = detail.get("name", "?")
    rel = next((r for r in detail.get("releases", []) if r.get("version") == version), None)
    if rel is None:
        raise VersionError([f"{name} has no version {version} in the registry"])
    if rel.get("yanked"):
        reason = f": {rel['reason']}" if rel.get("reason") else ""
        raise VersionError([f"{name} {version} was withdrawn (yanked){reason}"])
    if core and rel.get("nest") and not SpecifierSet(rel["nest"]).contains(core, prereleases=True):
        raise VersionError([f"{name} {version} works with nest-core {rel['nest']}; this is {core}"])
    return rel


def _download(
    detail: dict[str, Any], version: str, environ: Mapping[str, str], staging: Path
) -> tuple[Path, list[str]]:
    """The version's wheel, checked (sha256, signature), unpacked into a folder of its
    own under ``staging``; and what it requires (its Requires-Dist)."""
    from nest.remote import _client, registry_url, token_for  # noqa: PLC0415
    from nest.signing import check  # noqa: PLC0415

    name = detail.get("name", "?")
    wheels = [
        f
        for f in detail.get("files", [])
        if f.get("kind") == "wheel" and f.get("version") == version
    ]
    if not wheels:
        raise VersionError([f"{name} {version} has no wheel in the registry"])
    file = wheels[0]
    problems = check(name, file)
    if problems:
        raise VersionError(problems)
    url = registry_url(environ).rstrip("/")
    with _client(url, token_for(url, environ)) as c:
        r = c.get(f"/files/{file['sha256']}/{file['filename']}")
    if r.status_code != 200:
        raise VersionError([f"{file['filename']}: the registry answered {r.status_code}"])
    if hashlib.sha256(r.content).hexdigest() != file["sha256"]:
        raise VersionError([f"{file['filename']} is not the file the registry lists (sha256)"])
    target = staging / f"{_norm(detail['dist'])}-{version}"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as wheel:
        for member in wheel.namelist():  # nothing outside its folder
            if member.startswith(("/", "\\")) or ".." in Path(member).parts:
                raise VersionError([f"{file['filename']} holds a path outside itself: {member}"])
        if any(n.endswith((".so", ".pyd", ".dylib")) for n in wheel.namelist()):
            raise VersionError([f"{file['filename']} is not pure Python; a site takes only those"])
        wheel.extractall(target)
    meta = next(target.glob("*.dist-info/METADATA"), None)
    requires = (
        Parser().parsestr(meta.read_text(encoding="utf-8")).get_all("Requires-Dist") or []
        if meta
        else []
    )
    return target, requires


def _needs(staged: dict[str, Staged], have: dict[str, str | None]) -> list[str]:
    """What the staged versions require and will not have after the change."""
    from packaging.requirements import Requirement  # noqa: PLC0415

    problems = []
    for s in staged.values():
        for line in s.requires:
            req = Requirement(line)
            if req.marker is not None and not req.marker.evaluate({"extra": ""}):
                continue
            dist = _norm(req.name)
            got = have.get(dist)
            if got is None:
                problems.append(f"{s.name} {s.version} needs {req}, which this site does not have")
            elif req.specifier and not req.specifier.contains(got, prereleases=True):
                problems.append(f"{s.name} {s.version} needs {req}; this site would have {got}")
    return problems


def _environment_versions(workspace: Path) -> dict[str, str | None]:
    """Every distribution's version as the site runs now (overlay in use, then image)."""
    have: dict[str, str | None] = {}
    for d in metadata.distributions():
        have.setdefault(_norm(d.metadata["Name"] or ""), d.version)
    return have


# --- changing --------------------------------------------------------------------------------


def _staged_entry(folder: Path, name: str) -> Any:
    """A staged version's catalog entry (its manifest, inside the unpacked wheel)."""
    from nest.catalog import Entry  # noqa: PLC0415

    for path in sorted(folder.rglob(MANIFEST_FILE)):
        m = load_manifest(path.parent)
        if m.name == name:
            return Entry(manifest=m, source="package", package=None)
    return None


def _make_in_new_process(app_dir: Path, environ: Mapping[str, str]) -> tuple[bool, str]:
    """The application made in a fresh interpreter with the pins as they are written
    (its migrations up: NEST_MIGRATE=auto): whether it starts, and what it said."""
    code = (
        "import sys\n"
        "from nest.host import close_providers, create_app\n"
        "nest = create_app(sys.argv[1]).state.nest\n"
        "close_providers(nest)\n"
    )
    env = {**environ, "NEST_MIGRATE": "auto"}
    done = subprocess.run(  # noqa: S603 - our interpreter and our code
        [sys.executable, "-c", code, str(app_dir)],
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-12:])
    return done.returncode == 0, tail


def change(
    app_dir: str | Path,
    wanted: Mapping[str, str],
    environ: Mapping[str, str] | None = None,
    *,
    say: Callable[[str], None] = print,
    who: str = "",
) -> list[str]:
    """Take modules to the versions asked ({name: version, or "image"}); what was done."""
    from nest.modules import _record  # noqa: PLC0415

    app_dir = Path(app_dir).resolve()
    environ = dict(os.environ if environ is None else environ)
    workspace = resolve_workspace(load_manifest(app_dir).name, environ)
    asked = {"versions": [f"{n}={v}" for n, v in wanted.items()]}
    try:
        done = _change(app_dir, dict(wanted), environ, workspace, say)
    except VersionError as e:
        _record(workspace, who, asked, "refused", e.problems)
        raise
    _record(workspace, who, asked, "done", done)
    return done


def _change(
    app_dir: Path,
    wanted: dict[str, str],
    environ: dict[str, str],
    workspace: Path,
    say: Callable[[str], None],
) -> list[str]:
    from nest.catalog import Catalog  # noqa: PLC0415
    from nest.host import close_providers, create_app  # noqa: PLC0415
    from nest.ops import backup  # noqa: PLC0415
    from nest.remote import RemoteError, package  # noqa: PLC0415

    overlay.activate(workspace)
    catalog = Catalog.discover(app_dir)
    pins = overlay.load_pins(workspace)
    before = dict(pins)
    core = _core()
    staging = overlay.folder(workspace) / ".staging"
    shutil.rmtree(staging, ignore_errors=True)
    staged: dict[str, Staged] = {}
    dropped: dict[str, str] = {}  # dist: name, back to the image's version
    problems: list[str] = []

    for name, version in wanted.items():
        entry, _ = catalog.find(name)
        running = entry.manifest.module.version if entry is not None else None
        if version == IMAGE:
            dist = dist_of(entry)
            if dist is None or dist not in pins:
                problems.append(f"{name} runs the image's version already")
            else:
                dropped[dist] = name
            continue
        try:
            detail = package(name, None, environ)
            _release(detail, version, core)
            if _norm(detail["dist"]) == CORE:
                raise VersionError([f"{CORE} is the image's: it changes with the image"])
            if running == version and _norm(detail["dist"]) not in dropped:
                raise VersionError([f"{name} runs {version} already"])
            folder, requires = _download(detail, version, environ, staging)
        except (VersionError, RemoteError) as e:
            problems += e.problems
            continue
        staged[_norm(detail["dist"])] = Staged(
            name, _norm(detail["dist"]), version, folder, requires, running
        )
        say(f"{name} {version}: downloaded and checked")
    if problems:
        shutil.rmtree(staging, ignore_errors=True)
        raise VersionError(problems)

    # what each will need, as the site will be
    have = _environment_versions(workspace)
    for dist in dropped:
        have[dist] = overlay.image_version(dist, workspace)
    for dist, s in staged.items():
        have[dist] = s.version
    problems = _needs(staged, have)
    if problems:
        shutil.rmtree(staging, ignore_errors=True)
        raise VersionError(problems)

    # backed up, then the downgrades' migrations taken down with the code they have now
    nest_now = create_app(app_dir, environ={**environ, "NEST_MIGRATE": "off"}).state.nest
    taken_down: list[str] = []
    try:
        archive = backup(nest_now, keep=0)
        say(f"backed up to {archive}")
        for s in staged.values():
            if s.current is None or _vkey(s.version) >= _vkey(s.current):
                continue
            taken_down += _migrate_down_to(nest_now, catalog, s, say)
        for dist, name in dropped.items():
            image = overlay.image_version(dist, workspace)
            entry, _ = catalog.find(name)
            if entry is not None and image and _vkey(image) < _vkey(entry.manifest.module.version):
                say(f"{name}: the image's {image} is older than {entry.manifest.module.version}")
                problems.append(
                    f"{name}: going back to the image's older {image} is a downgrade: "
                    f"choose version {image} instead, so its migrations are taken down first"
                )
    finally:
        close_providers(nest_now)
    if problems:
        shutil.rmtree(staging, ignore_errors=True)
        raise VersionError(problems)

    # the pins, then the application made with them in a new process
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for dist, s in staged.items():
        final = overlay.Pin(dist, s.version, s.name, overlay.image_version(dist, workspace), now)
        shutil.rmtree(final.folder(workspace), ignore_errors=True)
        s.folder.replace(final.folder(workspace))
        pins[dist] = final
    for dist in dropped:
        pins.pop(dist, None)
    overlay.save_pins(workspace, pins)
    shutil.rmtree(staging, ignore_errors=True)
    ok, said = _make_in_new_process(app_dir, environ)
    if not ok:
        overlay.save_pins(workspace, before)
        back, said_back = _make_in_new_process(app_dir, environ)  # migrations up again
        problems = [f"the application does not start with these versions:\n{said}"]
        if not back:
            problems.append(
                f"and not with the versions before either:\n{said_back}\n"
                f"the backup is {archive} (nest restore, with the site stopped)"
            )
        raise VersionError(problems)
    _tidy(workspace, pins, before)
    done = [f"{s.name} {s.current or '—'} → {s.version}" for s in staged.values()]
    done += [f"{name} → the image's version" for name in dropped.values()]
    if taken_down:
        done.append("migrations taken down: " + ", ".join(taken_down))
    done.append(f"backup: {archive}")
    for line in done:
        say(line)
    return done


def _migrate_down_to(nest: Any, catalog: Any, s: Staged, say: Callable[[str], None]) -> list[str]:
    """Take a module's tables down to the newest revision its older version knows."""
    try:
        from nest_db import migrate  # noqa: PLC0415
    except ImportError:
        return []
    entry, _ = catalog.find(s.name)
    m_now = migrate.for_entry(entry) if entry is not None else None
    if m_now is None or "nest.db" not in nest.bindings.by_interface:
        return []
    older = _staged_entry(s.folder, s.name)
    m_old = migrate.for_entry(older) if older is not None else None
    heads = sorted(migrate.heads(m_old)) if m_old is not None else []
    if len(heads) > 1:
        raise VersionError([f"{s.name} {s.version} has several migration heads: {heads}"])
    target = heads[0] if heads else "base"
    db = nest.bindings.get("nest.db")
    if migrate.current(db, m_now) == ({target} if target != "base" else set()):
        return []
    script = m_now.script()
    if target != "base" and script.get_revision(target) is None:
        raise VersionError(
            [f"{s.name}: its migrations do not know {target}, the revision {s.version} needs"]
        )
    say(f"{s.name}: migrations taken down to {target}")
    migrate.downgrade(db, m_now, target)
    return [f"{s.name} → {target}"]


def _tidy(workspace: Path, pins: dict[str, overlay.Pin], before: dict[str, overlay.Pin]) -> None:
    """Folders no pin names, now or just before (those the reload still takes out), go."""
    keep = {p.folder(workspace).name for p in [*pins.values(), *before.values()]}
    for child in overlay.folder(workspace).iterdir():
        if child.is_dir() and not child.name.startswith(".") and child.name not in keep:
            shutil.rmtree(child, ignore_errors=True)


# --- migrations, by hand ----------------------------------------------------------------------


def migrations(nest: Any, name: str) -> dict[str, Any] | None:
    """A module's migrations: every revision (newest first), which are applied, and the
    revision its code expects; None when it keeps no tables."""
    try:
        from nest_db import migrate  # noqa: PLC0415
    except ImportError:
        return None
    unit = nest.plan.unit(name)
    m = migrate.for_entry(unit.entry) if unit is not None else None
    if m is None or "nest.db" not in nest.bindings.by_interface:
        return None
    db = nest.bindings.get("nest.db")
    script = m.script()
    current = migrate.current(db, m)
    applied: set[str] = set()
    for head in current:
        for rev in script.iterate_revisions(head, "base"):
            applied.add(rev.revision)
    revisions = [
        {
            "id": rev.revision,
            "message": (rev.doc or "").strip().splitlines()[0] if rev.doc else "",
            "applied": rev.revision in applied,
            "current": rev.revision in current,
        }
        for rev in script.walk_revisions()
    ]
    head = sorted(migrate.heads(m))
    return {
        "revisions": revisions,
        "current": sorted(current),
        "head": head,
        "state": "current" if set(head) == current else "behind" if applied else "none",
    }


def migrate_to(
    app_dir: str | Path,
    name: str,
    target: str,
    environ: Mapping[str, str] | None = None,
    *,
    say: Callable[[str], None] = print,
    who: str = "",
) -> list[str]:
    """Move a module's migrations to ``target`` (a revision, "head" or "base"), up or down,
    after a backup. Below the revision its code expects, the module may fail until it is
    migrated up again; that is the administrator's choice, said before."""
    from nest.host import close_providers, create_app  # noqa: PLC0415
    from nest.modules import _record  # noqa: PLC0415
    from nest.ops import backup  # noqa: PLC0415

    app_dir = Path(app_dir).resolve()
    environ = dict(os.environ if environ is None else environ)
    workspace = resolve_workspace(load_manifest(app_dir).name, environ)
    asked = {"migrate": [f"{name}={target}"]}
    nest = create_app(app_dir, environ={**environ, "NEST_MIGRATE": "off"}).state.nest
    try:
        from nest_db import migrate  # noqa: PLC0415

        unit = nest.plan.unit(name)
        m = migrate.for_entry(unit.entry) if unit is not None else None
        if m is None:
            raise VersionError([f"{name} keeps no tables in this application"])
        db = nest.bindings.get("nest.db")
        script = m.script()
        current = migrate.current(db, m)
        heads = migrate.heads(m)
        goal = sorted(heads)[0] if target == "head" and len(heads) == 1 else target
        if goal not in ("base", "heads") and script.get_revision(goal) is None:
            raise VersionError([f"{name} has no revision {target}"])
        if current == ({goal} if goal != "base" else set()):
            raise VersionError([f"{name} is at {target} already"])
        # up when every applied head is below the goal (or nothing is applied); else down
        below_goal = (
            {r.revision for r in script.iterate_revisions(goal, "base")}
            if goal != "base"
            else set()
        )
        up = not current or (goal != "base" and current <= below_goal)
        archive = backup(nest, keep=0)
        say(f"backed up to {archive}")
        if up:
            migrate.upgrade(db, m, goal)
            done = [f"{name}: migrated up to {goal}"]
        else:
            migrate.downgrade(db, m, goal)
            done = [f"{name}: migrated down to {goal}"]
        done.append(f"backup: {archive}")
    except VersionError as e:
        _record(workspace, who, asked, "refused", e.problems)
        raise
    except Exception as e:  # noqa: BLE001 - alembic says why, in its words
        _record(workspace, who, asked, "refused", [str(e)])
        raise VersionError([f"{name}: {e}"]) from e
    finally:
        close_providers(nest)
    _record(workspace, who, asked, "done", done)
    for line in done:
        say(line)
    return done
