"""Installing packages into an application: what the server's administrator does.

An application's admin panel enables what is installed; it never installs. Installing is
done on the server, by its administrator (``nest packages``, or the keeper app's pages),
and only from the **registry**: the packages trusted on this server.

* Nest's own: every package in the Nest checkout this Nest runs from (its modules,
  engines and subsystems, providers, interfaces, themes): your own code.
* Others, listed in a registry file (``$NEST_REGISTRY``, else ``~/.config/nest/registry.yml``),
  each pinned so that what was vetted is what comes: a git source at a commit (40
  hexadecimal digits, never a branch), or a package index at an exact version.

      packages:
        - {name: shop, dist: nest-shop, version: "1.2.0", type: module, title: Shop,
           git: "https://example.org/nest-shop.git", rev: "3f2c...40 hex"}
        - {name: forms-pro, dist: nest-forms-pro, version: "2.0.1", type: module,
           index: "https://pypi.org/simple"}

To install is to add the package to the application's contract and environment: its
``pyproject.toml`` (the dependency, and where it comes from), its ``module.yml`` deps
(the version range, under its ecosystem), then ``uv sync``. It is not added to the
application's modules: it arrives *installed, not used*, and the application's
administrator adds it in the panel's Modules page. If anything fails, both files are put
back as they were. To remove is the reverse, refused while the application lists it
(uninstall it there first).

In a container, the environment is the image's: install in development, commit, build.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nest.manifest import MANIFEST_FILE, ManifestError, load_manifest

INSTALLABLE = ("module", "subsystem", "content", "provider", "interface", "theme")
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_DIST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REV = re.compile(r"^[0-9a-f]{40}$")
_VERSION = re.compile(r"^\d+(\.\d+){1,3}([a-z0-9.+-]*)$")
SKIP = {".venv", "node_modules", "__pycache__", ".git", "applications"}


class PackageError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass
class Offer:
    """A package this server trusts, and where it comes from."""

    name: str
    dist: str
    version: str
    type: str
    title: str
    description: str
    ecosystem: str = "nest"
    source: str = "nest"  # nest (the checkout) | registry (the file)
    path: Path | None = None  # a path source (Nest's own)
    git: str | None = None
    rev: str | None = None
    index: str | None = None
    part_of: str | None = None
    interface: str | None = None  # an interface's name (nest.db), as applications bind it
    deps: list[str] = field(default_factory=list)


@dataclass
class PackageInfo:
    offer: Offer
    installed: bool  # in the application's environment (asked for, or with another)
    used: bool  # the application lists it (enabled or not), binds it, or its theme
    needed_by: list[str] = field(default_factory=list)  # installed packages that need it
    direct: bool = False  # the application asks for it (pyproject.toml): it may remove it


# --- the registry ------------------------------------------------------------------------


def nest_home(environ: Mapping[str, str] | None = None) -> Path | None:
    """The Nest checkout this Nest runs from ($NEST_HOME, else found from nest-core)."""
    environ = os.environ if environ is None else environ
    if environ.get("NEST_HOME"):
        return Path(environ["NEST_HOME"]).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "nest-core" / "pyproject.toml").is_file():
            return parent
    return None


def registry(environ: Mapping[str, str] | None = None) -> dict[str, Offer]:
    """Every package this server trusts, by name; the registry file's after Nest's own."""
    environ = os.environ if environ is None else environ
    offers: dict[str, Offer] = {}
    home = nest_home(environ)
    if home is not None:
        for manifest_path in sorted(home.rglob(MANIFEST_FILE)):
            if SKIP & set(manifest_path.relative_to(home).parts):
                continue
            project = _project_of(manifest_path.parent)
            if project is None:
                continue
            try:
                m = load_manifest(manifest_path.parent)
            except ManifestError:
                continue
            if m.type not in INSTALLABLE:
                continue
            dist = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["name"]
            offers[m.name] = Offer(
                name=m.name,
                dist=dist,
                version=m.module.version,
                type=m.type,
                title=m.module.title or m.name,
                description=" ".join((m.module.description or "").split()),
                ecosystem=_ecosystem(m),
                path=project.parent,
                part_of=m.part_of,
                interface=m.interface.name if m.interface else None,
                deps=sorted(m.deps),
            )
    file = Path(environ.get("NEST_REGISTRY") or Path.home() / ".config" / "nest" / "registry.yml")
    if file.is_file():
        for offer in read_registry(file):
            offers[offer.name] = offer
    return offers


def _project_of(folder: Path) -> Path | None:
    """The pyproject.toml of the distribution a manifest's package is in."""
    for candidate in (folder, *list(folder.parents)[:3]):
        project = candidate / "pyproject.toml"
        if project.is_file():
            return project
    return None


def _ecosystem(m: Any) -> str:
    from nest.catalog import Entry  # noqa: PLC0415
    from nest.contract import load_contracts  # noqa: PLC0415
    from nest.resolve import ecosystem_of  # noqa: PLC0415

    try:
        return ecosystem_of(Entry(manifest=m, source="package"), load_contracts())
    except Exception:  # noqa: BLE001
        return "nest"


def read_registry(file: Path) -> list[Offer]:
    """A registry file's packages, each checked: pinned, named, typed."""
    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    items = raw.get("packages") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise PackageError([f"{file}: expected a 'packages:' list"])
    problems, offers = [], []
    for i, item in enumerate(items):
        where = f"{file}: package {i + 1}"
        if not isinstance(item, dict):
            problems.append(f"{where} is not a mapping")
            continue
        name, dist, version = (
            str(item.get("name", "")),
            str(item.get("dist", "")),
            str(item.get("version", "")),
        )
        if not _NAME.match(name):
            problems.append(f"{where}: 'name' is a package name, lower-case")
        if not _DIST.match(dist):
            problems.append(f"{where}: 'dist' is the Python distribution's name")
        if not _VERSION.match(version):
            problems.append(f"{where}: 'version' is an exact version (1.2.0), not a range")
        git, rev, index = item.get("git"), item.get("rev"), item.get("index")
        if bool(git) == bool(index):
            problems.append(f"{where}: give either 'git' (with 'rev') or 'index'")
        if git and not (str(git).startswith("https://") and _REV.match(str(rev or ""))):
            problems.append(
                f"{where}: a git source is https, pinned at a commit (rev: 40 hex digits)"
            )
        if index and not str(index).startswith("https://"):
            problems.append(f"{where}: an index is https")
        kind = str(item.get("type", "module"))
        if kind not in INSTALLABLE:
            problems.append(f"{where}: 'type' is one of {', '.join(INSTALLABLE)}")
        offers.append(
            Offer(
                name=name,
                dist=dist,
                version=version,
                type=kind,
                title=str(item.get("title") or name),
                description=str(item.get("description") or ""),
                ecosystem=str(item.get("ecosystem") or "nest"),
                source="registry",
                git=str(git) if git else None,
                rev=str(rev) if rev else None,
                index=str(index) if index else None,
                part_of=item.get("part_of"),
            )
        )
    if problems:
        raise PackageError(problems)
    return offers


# --- an application's ------------------------------------------------------------------------


def _pyproject(app_dir: Path) -> dict[str, Any]:
    file = app_dir / "pyproject.toml"
    if not file.is_file():
        raise PackageError(
            [f"{app_dir} has no pyproject.toml: its packages are installed with Nest's"]
        )
    return tomllib.loads(file.read_text(encoding="utf-8"))


def _installed(app_dir: Path) -> dict[str, str]:
    """The application's dependencies, by distribution: their version ranges."""
    from packaging.requirements import Requirement  # noqa: PLC0415

    deps = _pyproject(app_dir).get("project", {}).get("dependencies", [])
    return {(r := Requirement(d)).name.lower(): str(r.specifier) for d in deps}


def status(app_dir: str | Path, environ: Mapping[str, str] | None = None) -> list[PackageInfo]:
    """Every package of the registry: installed in the application or not, used or not."""
    from nest import composition  # noqa: PLC0415
    from nest.workspace import resolve_workspace  # noqa: PLC0415

    app_dir = Path(app_dir).resolve()
    environ = dict(os.environ if environ is None else environ)
    offers = registry(environ)
    installed = _installed(app_dir)
    manifest = load_manifest(app_dir)
    listed = (
        {i.name for i in manifest.modules}
        | set(manifest.bind)
        | {p for b in manifest.bind.values() for p in b.providers}
    )
    if manifest.application and manifest.application.theme:
        listed.add(manifest.application.theme)
    listed |= set(composition.load(resolve_workspace(manifest.name, environ)))
    direct = {o.name for o in offers.values() if o.dist.lower() in installed}
    present = set(direct)  # and what they bring with them
    stack = list(direct)
    while stack:
        offer = offers.get(stack.pop())
        for dep in offer.deps if offer else []:
            if dep in offers and dep not in present:
                present.add(dep)
                stack.append(dep)
    needed: dict[str, set[str]] = {}
    for name in present:
        for dep in offers[name].deps:
            needed.setdefault(dep, set()).add(name)
    bound = set(manifest.bind)
    return [
        PackageInfo(
            offer=o,
            installed=o.name in present,
            used=o.name in listed or (o.interface is not None and o.interface in bound),
            needed_by=sorted(n for n in needed.get(o.name, set()) if n != o.name),
            direct=o.name in direct,
        )
        for o in sorted(offers.values(), key=lambda o: (o.type, o.name))
    ]


def _manifest_dir(offer: Offer) -> Path:
    assert offer.path is not None
    if (offer.path / MANIFEST_FILE).is_file():
        return offer.path
    for found in offer.path.rglob(MANIFEST_FILE):
        if not SKIP & set(found.relative_to(offer.path).parts):
            return found.parent
    return offer.path


def _range(version: str) -> str:
    """The range an application asks: this minor version on, below the next major."""
    major, minor = (version.split(".") + ["0"])[:2]
    return f">={major}.{minor},<{int(major) + 1}"


Runner = Callable[[list[str], Path], tuple[int, str]]


def run_uv(args: list[str], cwd: Path) -> tuple[int, str]:
    """``uv`` in the application's folder, its own environment (not the caller's)."""
    uv = os.environ.get("NEST_UV") or shutil.which("uv")
    if not uv:
        return 127, "uv is not installed on this server"
    env = {
        k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
    }
    done = subprocess.run(  # noqa: S603 - our arguments, never a shell
        [uv, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=900, check=False
    )
    return done.returncode, (done.stdout + done.stderr).strip()


def add(
    app_dir: str | Path,
    name: str,
    environ: Mapping[str, str] | None = None,
    *,
    runner: Runner | None = None,
    say: Callable[[str], None] = print,
) -> Offer:
    """Install a registry package in the application (installed, not used)."""
    runner = runner or run_uv
    app_dir = Path(app_dir).resolve()
    offer = registry(environ).get(name)
    if offer is None:
        raise PackageError([f"'{name}' is not in this server's registry"])
    installed = _installed(app_dir)
    if offer.dist.lower() in installed:
        raise PackageError([f"{name} is installed already"])
    spec = f"=={offer.version}" if offer.source == "registry" else _range(offer.version)
    files = _keep(app_dir)
    try:
        _add_dependency(app_dir, offer, spec)
        _add_dep_to_manifest(app_dir, offer, spec)
        say(f"{app_dir.name}: {offer.dist}{spec} added to pyproject.toml and module.yml")
        code, out = runner(["sync"], app_dir)
        if code != 0:
            raise PackageError([f"uv sync failed:\n{out}"])
        say(f"{app_dir.name}: installed {offer.dist} {offer.version}")
    except Exception:
        _restore(files)
        runner(["sync"], app_dir)  # the environment as the files say again
        raise
    return offer


def remove(
    app_dir: str | Path,
    name: str,
    environ: Mapping[str, str] | None = None,
    *,
    runner: Runner | None = None,
    say: Callable[[str], None] = print,
) -> Offer:
    """Take a package out of the application, if it neither lists nor needs it."""
    runner = runner or run_uv
    app_dir = Path(app_dir).resolve()
    info = {i.offer.name: i for i in status(app_dir, environ)}.get(name)
    if info is None or not info.installed:
        raise PackageError([f"{name} is not installed in {app_dir.name}"])
    if not info.direct:
        raise PackageError([f"{name} comes with {', '.join(info.needed_by)}; it goes with them"])
    if info.used:
        raise PackageError(
            [f"{app_dir.name} uses {name}: uninstall it in its admin panel (Modules) first"]
        )
    if info.needed_by:
        raise PackageError(
            [f"{name} is needed by {', '.join(info.needed_by)}, installed in {app_dir.name}"]
        )
    files = _keep(app_dir)
    try:
        _remove_dependency(app_dir, info.offer)
        _remove_dep_from_manifest(app_dir, info.offer)
        code, out = runner(["sync"], app_dir)
        if code != 0:
            raise PackageError([f"uv sync failed:\n{out}"])
        say(f"{app_dir.name}: removed {info.offer.dist}")
    except Exception:
        _restore(files)
        runner(["sync"], app_dir)
        raise
    return info.offer


# --- editing the files, keeping their comments -------------------------------------------------


def _keep(app_dir: Path) -> dict[Path, str]:
    return {
        p: p.read_text(encoding="utf-8")
        for p in (app_dir / "pyproject.toml", app_dir / MANIFEST_FILE)
    }


def _restore(files: dict[Path, str]) -> None:
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")


def _add_dependency(app_dir: Path, offer: Offer, spec: str) -> None:
    path = app_dir / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)^\]", text)
    if m is None:
        raise PackageError([f"{path}: no [project] dependencies list to add to"])
    line = f'    "{offer.dist}{spec}",\n'
    text = text[: m.end(1)] + line + text[m.end(1) :]
    sources = tomllib.loads(text).get("tool", {}).get("uv", {}).get("sources", {})
    if offer.dist not in sources:
        entry = _source(app_dir, offer)
        if entry:
            if re.search(r"(?m)^\[tool\.uv\.sources\]\s*$", text):
                text = re.sub(
                    r"(?m)^(\[tool\.uv\.sources\]\s*\n)",
                    lambda mm: mm.group(1) + f"{offer.dist} = {entry}\n",
                    text,
                    count=1,
                )
            else:
                text = text.rstrip("\n") + f"\n\n[tool.uv.sources]\n{offer.dist} = {entry}\n"
    tomllib.loads(text)  # still TOML
    path.write_text(text, encoding="utf-8")


def _source(app_dir: Path, offer: Offer) -> str | None:
    if offer.path is not None:
        rel = os.path.relpath(offer.path, app_dir)
        return f'{{ path = "{Path(rel).as_posix()}", editable = true }}'
    if offer.git:
        return f'{{ git = "{offer.git}", rev = "{offer.rev}" }}'
    return None  # an index: the default one (PyPI), at the exact version


def _remove_dependency(app_dir: Path, offer: Offer) -> None:
    path = app_dir / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf'(?m)^\s*"{re.escape(offer.dist)}[^"]*",?[^\n]*\n')
    text, n = pattern.subn("", text, count=1)
    if not n:
        raise PackageError([f"{path}: {offer.dist} is not among its dependencies"])
    tomllib.loads(text)
    path.write_text(text, encoding="utf-8")


def _add_dep_to_manifest(app_dir: Path, offer: Offer, spec: str) -> None:
    path = app_dir / MANIFEST_FILE
    text = path.read_text(encoding="utf-8")
    line = f'    {offer.name}: "{spec}"\n'
    group = re.search(
        rf"(?m)^deps:\s*\n(?:(?:  .*|\s*)\n)*?  {re.escape(offer.ecosystem)}:\s*\n", text
    )
    if group is not None:
        text = text[: group.end()] + line + text[group.end() :]
    elif re.search(r"(?m)^deps:\s*$", text):
        text = re.sub(
            r"(?m)^(deps:\s*\n)",
            lambda m: m.group(1) + f"  {offer.ecosystem}:\n" + line,
            text,
            count=1,
        )
    else:
        text = text.rstrip("\n") + f"\n\ndeps:\n  {offer.ecosystem}:\n{line}"
    path.write_text(text, encoding="utf-8")
    load_manifest(app_dir)  # still a manifest


def _remove_dep_from_manifest(app_dir: Path, offer: Offer) -> None:
    path = app_dir / MANIFEST_FILE
    text = path.read_text(encoding="utf-8")
    text = re.sub(rf'(?m)^    {re.escape(offer.name)}:\s*"[^"]*"[^\n]*\n', "", text, count=1)
    path.write_text(text, encoding="utf-8")
    load_manifest(app_dir)
