"""The registry's work: tokens, reading what a wheel says it is, publishing, and the index.

A publish is refused, with the reason, unless:

* it presents a token of an active account (made on its Tokens page, kept as a hash)
  that may publish here: with ``publishers: approved`` (the default), an account with the
  ``publisher`` role, which the registry's administrators give, or an administrator;
  with ``publishers: anyone``, any account;
* the file is a wheel (or the source archive of a release already published) of a sane
  name and size, read without unpacking: its METADATA and its package's ``module.yml``;
* the manifest is a Nest manifest keeping its type's contract, saying which nest-core
  versions it works with (``nest:``), its version the wheel's version;
* the namespace is the publisher's (an id's first segment, acme in acme.module.widgets:
  the first account to publish in it owns it; ``nest`` is the administrators'), and so is
  the package: its owner (the first to publish it) or a maintainer the owner added;
* no file of that name was published before (a fix is a new version).
"""

from __future__ import annotations

import hashlib
import io
import re
import secrets
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import timedelta
from email.parser import Parser
from pathlib import Path
from typing import Any

import yaml
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from sqlalchemy import func, select, update

from nest.contract import load_contracts
from nest.manifest import ManifestError, parse_manifest
from nest_registry.models import (
    File,
    Maintainer,
    Namespace,
    Package,
    Release,
    SigningKey,
    Token,
    utcnow,
)

TOKEN_PREFIX = "nrt_"
USED_EVERY = timedelta(minutes=1)
_WHEEL = re.compile(
    r"^(?P<dist>[A-Za-z0-9_.]+)-(?P<version>[^-]+)(-\d[^-]*)?-[^-]+-[^-]+-[^-]+\.whl$"
)
_SDIST = re.compile(r"^(?P<dist>[A-Za-z0-9_.-]+?)-(?P<version>\d[^-]*)\.tar\.gz$")


class PublishError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


# --- tokens ----------------------------------------------------------------------------------


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def make_token(db: Any, user_id: int, name: str) -> tuple[str, Token]:
    """A new token: its secret (shown once, never stored) and what is kept of it."""
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError("a token needs a name, of at most 120 characters")
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    with db.session() as s, s.begin():
        row = Token(user_id=user_id, name=name, prefix=secret[:10], digest=digest(secret))
        s.add(row)
        s.flush()
        s.expunge(row)
    return secret, row


def tokens_of(db: Any, user_id: int) -> list[Token]:
    with db.session() as s:
        rows = list(
            s.scalars(select(Token).where(Token.user_id == user_id).order_by(Token.id.desc()))
        )
        for r in rows:
            s.expunge(r)
    return rows


def revoke(db: Any, user_id: int, token_id: int) -> bool:
    with db.session() as s, s.begin():
        done = s.execute(
            update(Token).where(Token.id == token_id, Token.user_id == user_id).values(revoked=True)
        )
    return bool(done.rowcount)


def user_of(db: Any, secret: str) -> int | None:
    """The account a token belongs to, if it is a live one (its last use noted)."""
    if not secret.startswith(TOKEN_PREFIX):
        return None
    with db.session() as s, s.begin():
        row = s.scalar(
            select(Token).where(Token.digest == digest(secret), Token.revoked.is_(False))
        )
        if row is None:
            return None
        now = utcnow()
        if row.last_used_at is None or now - row.last_used_at > USED_EVERY:
            row.last_used_at = now
        return row.user_id


# --- reading a wheel ---------------------------------------------------------------------------


@dataclass
class Read:
    dist: str
    version: str
    requires_python: str
    manifest: Any  # nest.manifest.Manifest; None for an index-only distribution
    raw: dict[str, Any]
    about: str = ""
    screenshot: tuple[str, bytes] | None = None  # a theme's picture: (its name, its bytes)
    summary: str = ""


def about_of(text: str) -> str:
    """The opening comment of a manifest, as prose: what its author says the package is.
    Lines of a paragraph are joined; list items and indented lines (an example) keep theirs."""
    raw: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            if raw or stripped:
                break
            continue
        body = stripped[1:]
        raw.append(body[1:] if body.startswith(" ") else body)
    paragraphs, current = [], []
    for line in raw:
        if not line.strip():
            if current:
                paragraphs.append(current)
            current = []
            continue
        kept = line.startswith((" ", "-", "*", "\t")) or (
            current and current[-1].startswith((" ", "-", "*"))
        )
        if current and not kept:
            current[-1] = current[-1] + " " + line.strip()
        else:
            current.append(line.rstrip())
    if current:
        paragraphs.append(current)
    return "\n\n".join("\n".join(p) for p in paragraphs).strip()


def read_wheel(filename: str, data: bytes, *, index_only: frozenset[str] = frozenset()) -> Read:
    """What a wheel says it is, without unpacking it: its METADATA and its module.yml."""
    m = _WHEEL.match(filename)
    if m is None:
        raise PublishError(400, f"'{filename}' is not a wheel's name")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
    except zipfile.BadZipFile:
        raise PublishError(400, f"{filename} is not a wheel (not a zip archive)") from None
    meta_names = [n for n in names if re.fullmatch(r"[^/]+\.dist-info/METADATA", n)]
    if len(meta_names) != 1:
        raise PublishError(400, f"{filename} has no single .dist-info/METADATA")
    meta = Parser().parsestr(z.read(meta_names[0]).decode("utf-8", "replace"))
    dist, version = meta.get("Name", ""), meta.get("Version", "")
    if canonicalize_name(dist) != canonicalize_name(m.group("dist")) or version != m.group(
        "version"
    ):
        raise PublishError(400, f"{filename}'s name does not match its METADATA ({dist} {version})")
    manifests = [n for n in names if re.fullmatch(r"[A-Za-z0-9_]+/module\.yml", n)]
    if not manifests and canonicalize_name(dist) in index_only:  # the host: the index only
        return Read(
            dist,
            version,
            meta.get("Requires-Python", "") or "",
            None,
            {},
            summary=meta.get("Summary", "") or "",
        )
    if len(manifests) != 1:
        raise PublishError(
            400,
            f"{filename} carries no module.yml in its package: is it a Nest package? (src/<package>/module.yml)",
        )
    text = z.read(manifests[0]).decode("utf-8")
    try:
        raw = yaml.safe_load(text)
        manifest = parse_manifest(raw, f"{filename}:{manifests[0]}", Path("/nonexistent"))
    except (yaml.YAMLError, ManifestError) as e:
        raise PublishError(400, f"{filename}'s module.yml cannot be read: {e}") from None
    shot = None
    picture = str((raw or {}).get("screenshot") or "")
    if picture and manifest.type == "theme":
        inside = f"{manifests[0].split('/')[0]}/{picture}"
        if inside in names and picture.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            shot = (picture.rsplit("/", 1)[-1], z.read(inside))
    return Read(
        dist=dist,
        version=version,
        requires_python=meta.get("Requires-Python", "") or "",
        manifest=manifest,
        raw=raw,
        about=about_of(text),
        screenshot=shot,
        summary=meta.get("Summary", "") or "",
    )


# --- publishing ----------------------------------------------------------------------------------


PUBLISHER = "publisher"  # the role that may publish, with publishers: approved


def may_publish(user: Any, publishers: str = "approved") -> bool:
    """Whether an account may publish here at all (what it may publish is decided after)."""
    return publishers == "anyone" or user.has(PUBLISHER)


def can_release(s: Any, package: Package, user: Any) -> bool:
    if user.has("admin") or package.owner_id == user.id:
        return True
    return (
        s.scalar(
            select(Maintainer.id).where(
                Maintainer.package_id == package.id, Maintainer.user_id == user.id
            )
        )
        is not None
    )


def publish(
    db: Any,
    storage: Any,
    user: Any,
    filename: str,
    data: bytes,
    *,
    official_prefix: str = "nest.",
    max_bytes: int = 50 * 1024 * 1024,
    publishers: str = "approved",
    index_only: frozenset[str] = frozenset(),
    signature: str = "",
    signer: str = "",
    require_signatures: bool = False,
    visibility: str = "public",
) -> dict[str, Any]:
    """Keep a wheel (or a published release's source archive); what was published."""
    if not may_publish(user, publishers):
        raise PublishError(
            403,
            "this account may not publish here; the registry's administrators approve publishers",
        )
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise PublishError(400, "a file's name only")
    if len(data) > max_bytes:
        raise PublishError(413, f"{filename} is larger than {max_bytes // (1024 * 1024)} MB")
    sha = hashlib.sha256(data).hexdigest()
    _check_signature(db, user, filename, sha, signature, signer, require_signatures)
    if visibility not in ("public", "private"):
        raise PublishError(400, "visibility is public or private")
    if filename.endswith(".tar.gz"):
        return _publish_sdist(db, storage, user, filename, data, signature, signer)
    read = read_wheel(filename, data, index_only=index_only)
    if read.manifest is None:
        return _publish_index_only(db, storage, user, filename, data, read, signature, signer)
    m = read.manifest
    problems = load_contracts().validate(m)
    if problems:
        raise PublishError(400, f"{m.name}: " + "; ".join(problems))
    if not m.nest:
        raise PublishError(
            400, f'{m.name} does not say which nest-core versions it works with (nest: ">=0.2,<1")'
        )
    if m.type == "application":
        raise PublishError(400, "an application is deployed, not published")
    if m.module.version != read.version:
        raise PublishError(
            400, f"{m.name}'s module.yml says {m.module.version}, the wheel {read.version}"
        )
    try:
        Version(read.version)
    except InvalidVersion:
        raise PublishError(400, f"'{read.version}' is not a version") from None
    official = m.id.startswith(official_prefix)
    if official and not user.has("admin"):
        raise PublishError(
            403, f"ids under {official_prefix} are published by the registry's administrators"
        )
    dist = canonicalize_name(read.dist)
    sha = hashlib.sha256(data).hexdigest()
    with db.session() as s, s.begin():
        if s.scalar(select(File.id).where(File.filename == filename)) is not None:
            raise PublishError(409, f"{filename} was published already; a fix is a new version")
        package = s.scalar(select(Package).where(Package.name == m.name))
        by_dist = s.scalar(select(Package).where(Package.dist == dist))
        if package is None and by_dist is not None:
            raise PublishError(
                403, f"the distribution {dist} belongs to the package {by_dist.name}"
            )
        if package is not None and package.dist != dist:
            raise PublishError(403, f"{m.name} is published as {package.dist}, not {dist}")
        if package is not None and not can_release(s, package, user):
            raise PublishError(
                403, f"{m.name} belongs to another account; its owner may make you a maintainer"
            )
        if package is None:
            space = m.id.split(".")[0]
            owner = s.scalar(select(Namespace).where(Namespace.name == space))
            if owner is None and not official:
                s.add(Namespace(name=space, owner_id=user.id))
            elif owner is not None and owner.owner_id != user.id and not user.has("admin"):
                raise PublishError(403, f"the namespace {space} belongs to another account")
            package = Package(name=m.name, dist=dist, owner_id=user.id, visibility=visibility)
            s.add(package)
            s.flush()
        release = s.scalar(
            select(Release).where(Release.package_id == package.id, Release.version == read.version)
        )
        if release is None:
            release = Release(
                package_id=package.id,
                version=read.version,
                type=m.type,
                ecosystem=_ecosystem(m),
                title=m.module.title or m.name,
                description=" ".join((m.module.description or "").split()),
                nest=m.nest,
                requires_python=read.requires_python,
                manifest=_public(read.raw),
                about=read.about,
                uploader_id=user.id,
            )
            s.add(release)
            s.flush()
            if read.screenshot is not None:
                shot_name, shot = read.screenshot
                shot_key = f"screenshots/{dist}/{read.version}/{shot_name}"
                storage.put(shot_key, shot, _image_type(shot_name))
                release.screenshot = shot_key
        key = f"files/{sha[:2]}/{sha}/{filename}"
        storage.put(key, data, "application/octet-stream")
        s.add(
            File(
                release_id=release.id,
                filename=filename,
                kind="wheel",
                sha256=sha,
                size=len(data),
                key=key,
                signature=signature,
                signer=signer,
            )
        )
    return {"name": m.name, "dist": dist, "version": read.version, "file": filename, "sha256": sha}


def _image_type(name: str) -> str:
    return {"png": "image/png", "webp": "image/webp"}.get(
        name.rsplit(".", 1)[-1].lower(), "image/jpeg"
    )


def _publish_index_only(
    db: Any,
    storage: Any,
    user: Any,
    filename: str,
    data: bytes,
    read: Read,
    signature: str = "",
    signer: str = "",
) -> dict[str, Any]:
    """The host (nest-core): in the index, so applications install everything from here, and
    not in the catalog (it is no package to add). Its administrators' only."""
    if not user.has("admin"):
        raise PublishError(403, f"{read.dist} is published by the registry's administrators")
    dist = canonicalize_name(read.dist)
    sha = hashlib.sha256(data).hexdigest()
    with db.session() as s, s.begin():
        if s.scalar(select(File.id).where(File.filename == filename)) is not None:
            raise PublishError(409, f"{filename} was published already; a fix is a new version")
        package = s.scalar(select(Package).where(Package.dist == dist))
        if package is None:
            package = Package(name=dist, dist=dist, owner_id=user.id, index_only=True)
            s.add(package)
            s.flush()
        release = s.scalar(
            select(Release).where(Release.package_id == package.id, Release.version == read.version)
        )
        if release is None:
            release = Release(
                package_id=package.id,
                version=read.version,
                type="core",
                title=dist,
                description=read.summary,
                nest="",
                requires_python=read.requires_python,
                manifest={},
                uploader_id=user.id,
            )
            s.add(release)
            s.flush()
        key = f"files/{sha[:2]}/{sha}/{filename}"
        storage.put(key, data, "application/octet-stream")
        s.add(
            File(
                release_id=release.id,
                filename=filename,
                kind="wheel",
                sha256=sha,
                size=len(data),
                key=key,
                signature=signature,
                signer=signer,
            )
        )
    return {"name": dist, "dist": dist, "version": read.version, "file": filename, "sha256": sha}


def _publish_sdist(
    db: Any,
    storage: Any,
    user: Any,
    filename: str,
    data: bytes,
    signature: str = "",
    signer: str = "",
) -> dict[str, Any]:
    m = _SDIST.match(filename)
    if m is None:
        raise PublishError(400, f"'{filename}' is not a source archive's name")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            tar.getmembers()
    except tarfile.TarError:
        raise PublishError(400, f"{filename} is not a gzipped tar archive") from None
    dist, version = canonicalize_name(m.group("dist")), m.group("version")
    sha = hashlib.sha256(data).hexdigest()
    with db.session() as s, s.begin():
        if s.scalar(select(File.id).where(File.filename == filename)) is not None:
            raise PublishError(409, f"{filename} was published already; a fix is a new version")
        package = s.scalar(select(Package).where(Package.dist == dist))
        release = (
            s.scalar(
                select(Release).where(Release.package_id == package.id, Release.version == version)
            )
            if package is not None
            else None
        )
        if release is None:
            raise PublishError(
                400, f"publish the wheel of {dist} {version} before its source archive"
            )
        if not can_release(s, package, user):
            raise PublishError(403, f"{package.name} belongs to another account")
        key = f"files/{sha[:2]}/{sha}/{filename}"
        storage.put(key, data, "application/gzip")
        s.add(
            File(
                release_id=release.id,
                filename=filename,
                kind="sdist",
                sha256=sha,
                size=len(data),
                key=key,
                signature=signature,
                signer=signer,
            )
        )
        name = package.name
    return {"name": name, "dist": dist, "version": version, "file": filename, "sha256": sha}


def _ecosystem(m: Any) -> str:
    from nest.catalog import Entry  # noqa: PLC0415
    from nest.resolve import ecosystem_of  # noqa: PLC0415

    try:
        return ecosystem_of(Entry(manifest=m, source="package"), load_contracts())
    except Exception:  # noqa: BLE001
        return "nest"


def _public(raw: dict[str, Any]) -> dict[str, Any]:
    """What the catalog shows of a manifest: what it is and what it needs, not its settings'
    defaults or anything else a package keeps for itself."""
    keep = ("module", "nest", "deps", "uses", "requires", "implements", "interface", "part_of",
            "extends", "facts", "provides", "admin", "docs", "preview")  # fmt: skip
    return {k: raw[k] for k in keep if k in raw}


# --- reading ------------------------------------------------------------------------------------


def _visible(query: Any, viewer: Any = None) -> Any:
    """Only what ``viewer`` may see: public packages, and a private one to its owner, its
    maintainers and the administrators; to anyone else it does not exist."""
    from sqlalchemy import exists, or_  # noqa: PLC0415

    if viewer is not None and viewer.has("admin"):
        return query
    if viewer is None:
        return query.where(Package.visibility == "public")
    maintains = exists().where(Maintainer.package_id == Package.id, Maintainer.user_id == viewer.id)
    return query.where(
        or_(Package.visibility == "public", Package.owner_id == viewer.id, maintains)
    )


def screenshot(db: Any, name: str, viewer: Any = None) -> tuple[str, str] | None:
    """The newest release's theme picture: (its storage key, its media type)."""
    with db.session() as s:
        p = s.scalar(_visible(select(Package).where(Package.name == name), viewer))
        if p is None:
            return None
        rows = [
            r for r in s.scalars(select(Release).where(Release.package_id == p.id)) if r.screenshot
        ]
    if not rows:
        return None
    key = max(rows, key=lambda r: _version_key(r.version)).screenshot
    return key, _image_type(key)


def projects(db: Any, viewer: Any = None) -> list[str]:
    """Every distribution published (normalised), for the index's root page."""
    with db.session() as s:
        return list(s.scalars(_visible(select(Package.dist), viewer).order_by(Package.dist)))


def files_of(
    db: Any, dist: str, viewer: Any = None
) -> tuple[Package, list[tuple[Release, File]]] | None:
    with db.session() as s:
        package = s.scalar(
            _visible(select(Package).where(Package.dist == canonicalize_name(dist)), viewer)
        )
        if package is None:
            return None
        rows = s.execute(
            select(Release, File)
            .join(File, File.release_id == Release.id)
            .where(Release.package_id == package.id)
        ).all()
        s.expunge_all()
    rows.sort(key=lambda rf: (_version_key(rf[0].version), rf[1].filename))
    return package, [(r, f) for r, f in rows]


def file_by(db: Any, sha: str, filename: str, viewer: Any = None) -> File | None:
    with db.session() as s:
        row = s.scalar(
            _visible(
                select(File)
                .join(Release, Release.id == File.release_id)
                .join(Package, Package.id == Release.package_id)
                .where(File.sha256 == sha, File.filename == filename),
                viewer,
            )
        )
        if row is not None:
            s.expunge(row)
        return row


def _fits(nest_range: str, core: str) -> bool:
    from packaging.specifiers import InvalidSpecifier, SpecifierSet  # noqa: PLC0415

    if not core or not nest_range:
        return True
    try:
        return SpecifierSet(nest_range).contains(core, prereleases=True)
    except InvalidSpecifier:
        return False


def catalog(
    db: Any, q: str = "", kind: str = "", core: str = "", viewer: Any = None
) -> list[dict[str, Any]]:
    """Every public package with its newest release, or, given a nest-core version
    (``core``), its newest release that works with it (those with none are left out):
    what search, ``nest packages`` and the keeper show. ``dep_dists`` are the
    distributions of the Nest packages it needs, so an installer takes them from here too."""
    with db.session() as s:
        packages = list(
            s.scalars(
                _visible(select(Package), viewer)
                .where(Package.index_only.is_(False))
                .order_by(Package.name)
            )
        )
        dists = {p.name: p.dist for p in packages}
        out = []
        for p in packages:
            releases = list(
                s.scalars(
                    select(Release).where(Release.package_id == p.id, Release.yanked.is_(False))
                )
            )
            fitting = [r for r in releases if _fits(r.nest, core)]
            if not fitting:
                continue
            latest = max(fitting, key=lambda r: _version_key(r.version))
            item = _item(
                p,
                latest,
                [r.version for r in sorted(releases, key=lambda r: _version_key(r.version))],
            )
            item["dep_dists"] = sorted(dists[d] for d in item["deps"] if d in dists)
            text = f"{p.name} {latest.title} {latest.description}".lower()
            if q and q.lower() not in text:
                continue
            if kind and latest.type != kind:
                continue
            out.append(item)
    return out


def package(db: Any, name: str, viewer: Any = None) -> dict[str, Any] | None:
    with db.session() as s:
        p = s.scalar(_visible(select(Package).where(Package.name == name), viewer))
        if p is None:
            return None
        releases = sorted(
            s.scalars(select(Release).where(Release.package_id == p.id)),
            key=lambda r: _version_key(r.version),
        )
        if not releases:
            return None
        live = [r for r in releases if not r.yanked] or releases
        item = _item(p, live[-1], [r.version for r in releases])
        files = (
            s.execute(select(File).join(Release).where(Release.package_id == p.id)).scalars().all()
        )
        item["files"] = [
            {
                "filename": f.filename,
                "sha256": f.sha256,
                "size": f.size,
                "kind": f.kind,
                "signature": f.signature,
                "key": f.signer,
                "key_fingerprint": _fp(f.signer),
                "version": next((r.version for r in releases if r.id == f.release_id), ""),
            }
            for f in files
        ]
        item["releases"] = [
            {
                "version": r.version,
                "nest": r.nest,
                "yanked": r.yanked,
                "reason": r.yank_reason,
                "published": r.created_at.isoformat() + "Z",
            }
            for r in releases
        ]
    return item


def _item(p: Package, r: Release, versions: list[str]) -> dict[str, Any]:
    m = r.manifest or {}
    return {
        "name": p.name,
        "dist": p.dist,
        "type": r.type,
        "ecosystem": r.ecosystem,
        "title": r.title,
        "description": r.description,
        "version": r.version,
        "versions": versions,
        "nest": r.nest,
        "requires_python": r.requires_python,
        "deps": sorted((m.get("deps") or {}).keys()) if isinstance(m.get("deps"), dict) else [],
        "uses": list(m.get("uses") or []),
        "part_of": m.get("part_of"),
        "extends": m.get("extends"),
        "preview": m.get("preview") if isinstance(m.get("preview"), dict) else None,
        "owner_id": p.owner_id,
        "visibility": p.visibility,
        "interface": (m.get("interface") or {}).get("name")
        if isinstance(m.get("interface"), dict)
        else None,
        "implements": list(m.get("implements") or []),
        "about": r.about,
        "screenshot": bool(r.screenshot),
    }


def _version_key(v: str) -> Any:
    try:
        return (0, Version(v))
    except InvalidVersion:
        return (1, v)


def counts(db: Any) -> dict[str, int]:
    with db.session() as s:
        return {
            "packages": s.scalar(select(func.count()).select_from(Package)) or 0,
            "releases": s.scalar(select(func.count()).select_from(Release)) or 0,
            "files": s.scalar(select(func.count()).select_from(File)) or 0,
        }


# --- who works on a package ------------------------------------------------------------------


class AccessError(Exception):
    pass


def people(db: Any, name: str) -> tuple[int, list[int]] | None:
    """A package's owner and maintainers, by account id."""
    with db.session() as s:
        p = s.scalar(select(Package).where(Package.name == name))
        if p is None:
            return None
        ids = list(
            s.scalars(
                select(Maintainer.user_id)
                .where(Maintainer.package_id == p.id)
                .order_by(Maintainer.id)
            )
        )
        return p.owner_id, ids


def add_maintainer(db: Any, name: str, actor: Any, user_id: int) -> None:
    """The owner (or an administrator) lets another account publish versions of it."""
    with db.session() as s, s.begin():
        p = s.scalar(select(Package).where(Package.name == name))
        if p is None:
            raise AccessError("no such package")
        if p.owner_id != actor.id and not actor.has("admin"):
            raise AccessError("only the package's owner chooses its maintainers")
        if user_id == p.owner_id:
            raise AccessError("the owner maintains it already")
        exists = s.scalar(
            select(Maintainer.id).where(
                Maintainer.package_id == p.id, Maintainer.user_id == user_id
            )
        )
        if exists is None:
            s.add(Maintainer(package_id=p.id, user_id=user_id))


def remove_maintainer(db: Any, name: str, actor: Any, user_id: int) -> None:
    from sqlalchemy import delete  # noqa: PLC0415

    with db.session() as s, s.begin():
        p = s.scalar(select(Package).where(Package.name == name))
        if p is None:
            raise AccessError("no such package")
        if p.owner_id != actor.id and not actor.has("admin"):
            raise AccessError("only the package's owner chooses its maintainers")
        s.execute(
            delete(Maintainer).where(Maintainer.package_id == p.id, Maintainer.user_id == user_id)
        )


def namespaces(db: Any) -> list[tuple[str, int]]:
    with db.session() as s:
        return [(n.name, n.owner_id) for n in s.scalars(select(Namespace).order_by(Namespace.name))]


# --- signatures --------------------------------------------------------------------------------


def _check_signature(
    db: Any, user: Any, filename: str, sha: str, signature: str, signer: str, required: bool
) -> None:
    from nest.signing import verify  # noqa: PLC0415

    if not signature and not signer:
        if required:
            raise PublishError(
                400,
                f"{filename} is not signed; this registry takes signed files only (nest keygen --register)",
            )
        return
    with db.session() as s:
        known = s.scalar(
            select(SigningKey.id).where(
                SigningKey.user_id == user.id,
                SigningKey.public == signer,
                SigningKey.revoked.is_(False),
            )
        )
    if known is None:
        raise PublishError(
            400,
            f"{filename} is signed by a key this account has not registered (nest keygen --register)",
        )
    if not verify(signer, filename, sha, signature):
        raise PublishError(400, f"{filename}'s signature does not hold")


def add_key(db: Any, user_id: int, public: str, name: str) -> SigningKey:
    from nest.signing import fingerprint, valid_public  # noqa: PLC0415

    public, name = public.strip(), (name.strip() or "key")[:120]
    if not valid_public(public):
        raise ValueError("not an Ed25519 public key (base64, 32 bytes): nest keygen prints one")
    with db.session() as s, s.begin():
        row = s.scalar(
            select(SigningKey).where(SigningKey.user_id == user_id, SigningKey.public == public)
        )
        if row is None:
            row = SigningKey(
                user_id=user_id, public=public, name=name, fingerprint=fingerprint(public)
            )
            s.add(row)
        row.revoked = False
        s.flush()
        s.expunge(row)
    return row


def keys_of(db: Any, user_id: int) -> list[SigningKey]:
    with db.session() as s:
        rows = list(
            s.scalars(
                select(SigningKey)
                .where(SigningKey.user_id == user_id)
                .order_by(SigningKey.id.desc())
            )
        )
        for r in rows:
            s.expunge(r)
    return rows


def revoke_key(db: Any, user_id: int, key_id: int) -> bool:
    with db.session() as s, s.begin():
        done = s.execute(
            update(SigningKey)
            .where(SigningKey.id == key_id, SigningKey.user_id == user_id)
            .values(revoked=True)
        )
    return bool(done.rowcount)


# --- visibility and withdrawn versions --------------------------------------------------------


def set_visibility(db: Any, name: str, actor: Any, visibility: str) -> None:
    """Public or private: the owner's or an administrator's to choose. To an account that
    cannot see a private package, it does not exist."""
    if visibility not in ("public", "private"):
        raise AccessError("visibility is public or private")
    with db.session() as s, s.begin():
        p = s.scalar(_visible(select(Package).where(Package.name == name), actor))
        if p is None:
            raise AccessError("no such package")
        if p.owner_id != actor.id and not actor.has("admin"):
            raise AccessError("only the package's owner chooses who may install it")
        p.visibility = visibility


def yank(
    db: Any, name: str, version: str, actor: Any, reason: str = "", undo: bool = False
) -> None:
    """Withdraw a version (or bring it back): installers pass it by unless asked for it
    exactly, so an application pinned to it keeps working. The owner's or an
    administrator's; its files stay."""
    with db.session() as s, s.begin():
        p = s.scalar(select(Package).where(Package.name == name))
        if p is None:
            raise AccessError("no such package")
        if p.owner_id != actor.id and not actor.has("admin"):
            raise AccessError("only the package's owner withdraws its versions")
        r = s.scalar(select(Release).where(Release.package_id == p.id, Release.version == version))
        if r is None:
            raise AccessError(f"{name} has no version {version}")
        r.yanked, r.yank_reason = (False, "") if undo else (True, reason.strip()[:300])


def _fp(public: str) -> str:
    from nest.signing import fingerprint  # noqa: PLC0415

    return fingerprint(public) if public else ""
