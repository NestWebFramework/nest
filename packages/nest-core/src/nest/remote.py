"""A remote Nest registry, from this side: where it is, who we are there, publishing to it,
and what it offers.

The registry is ``$NEST_REGISTRY_URL``, else the one ``nest login`` saved as the default,
else https://registry.nest-framework.org. ``nest login`` keeps a token per registry in
``~/.config/nest/credentials.yml`` (readable by its owner only). ``nest publish`` checks a
package as the registry will (its manifest, its contract, its boundaries, the nest-core
versions it works with), builds its wheel and source archive with uv, makes sure the
wheel carries its manifest, and uploads both with the token. Installing from it
(``nest packages APP add NAME --remote``) is nest.packages': the registry's Python index
becomes the only source of that package (``explicit``), so a package of the same name
elsewhere is never taken instead.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

DEFAULT = "https://registry.nest-framework.org"
TIMEOUT = 15.0


class RemoteError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def credentials_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "nest" / "credentials.yml"


def _credentials() -> dict[str, Any]:
    file = credentials_file()
    if not file.is_file():
        return {}
    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def registry_url(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    url = environ.get("NEST_REGISTRY_URL") or _credentials().get("default") or DEFAULT
    return str(url).rstrip("/")


def token_for(url: str, environ: Mapping[str, str] | None = None) -> str | None:
    environ = os.environ if environ is None else environ
    if environ.get("NEST_REGISTRY_TOKEN"):  # CI: a secret in the environment
        return environ["NEST_REGISTRY_TOKEN"]
    return (_credentials().get("tokens") or {}).get(url.rstrip("/"))


def _client(url: str, token: str | None = None) -> Any:
    import httpx  # noqa: PLC0415

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(base_url=url, headers=headers, timeout=TIMEOUT, follow_redirects=True)


def login(url: str, token: str) -> str:
    """Check the token with the registry, keep it; the account it is."""
    url = url.rstrip("/")
    with _client(url, token) as c:
        try:
            r = c.get("/api/v1/whoami")
        except Exception as e:  # noqa: BLE001
            raise RemoteError([f"{url} does not answer: {e}"]) from None
    if r.status_code != 200:
        raise RemoteError([f"{url} refused the token: {_detail(r)}"])
    data = _credentials()
    data.setdefault("tokens", {})[url] = token
    data["default"] = url
    file = credentials_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, file)
    return str(r.json().get("account", "?"))


def _detail(r: Any) -> str:
    try:
        return str(r.json().get("detail", r.text))
    except Exception:  # noqa: BLE001
        return f"{r.status_code} {r.text[:200]}"


# --- publishing -------------------------------------------------------------------------------


INDEX_ONLY = ("nest-core",)  # the host: no manifest, in the index only (its administrators')


def _dist_of(project: Path) -> tuple[str, str]:
    import tomllib  # noqa: PLC0415

    data = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return data["name"], data["version"]


def check_package(project: Path) -> tuple[Any, list[str]]:
    """The package's entry, and what the registry would refuse in it."""
    from nest.boundaries import check  # noqa: PLC0415
    from nest.catalog import Catalog, Entry  # noqa: PLC0415
    from nest.contract import load_contracts  # noqa: PLC0415
    from nest.manifest import ManifestError, load_manifest  # noqa: PLC0415

    found = list((project / "src").glob("*/module.yml"))
    if len(found) != 1:
        return None, [f"{project} has no src/<package>/module.yml (a package carries its manifest)"]
    try:
        manifest = load_manifest(found[0].parent)
    except ManifestError as e:
        return None, e.problems
    entry = Entry(manifest=manifest, source="local")
    problems = [f"{manifest.name}: {p}" for p in load_contracts().validate(manifest)]
    if not manifest.nest:
        problems.append(
            f"{manifest.name} does not say which nest-core versions it works with (nest:)"
        )
    if manifest.type == "application":
        problems.append("an application is deployed, not published")
    findings = check([entry], [*Catalog.discover(None), entry])
    problems += [str(f) for f in findings if f.level == "error"]
    return entry, problems


def build(project: Path, out: Path) -> list[Path]:
    uv = os.environ.get("NEST_UV") or shutil.which("uv")
    if not uv:
        raise RemoteError(["uv is not installed"])
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    done = subprocess.run(  # noqa: S603 - our arguments, never a shell
        [uv, "build", str(project), "--wheel", "--sdist", "-o", str(out)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if done.returncode != 0:
        raise RemoteError([f"uv build failed:\n{done.stdout}{done.stderr}"])
    files = sorted(out.glob("*.whl")) + sorted(out.glob("*.tar.gz"))
    if not any(f.suffix == ".whl" for f in files):
        raise RemoteError(["uv build made no wheel"])
    return files


def publish(
    project: str | Path,
    url: str | None = None,
    *,
    dry_run: bool = False,
    say: Callable[[str], None] = print,
    environ: Mapping[str, str] | None = None,
    private: bool = False,
) -> list[dict[str, Any]]:
    """Check, build and upload a package (its wheel, then its source archive), each file
    signed when there is a signing key (nest keygen); ``private``: a new package only its
    owner, maintainers and the administrators see."""
    project = Path(project).resolve()
    url = (url or registry_url(environ)).rstrip("/")
    dist, version = _dist_of(project)
    host = dist in INDEX_ONLY  # the host: published to the index only
    entry, problems = (None, []) if host else check_package(project)
    if problems:
        raise RemoteError(problems)
    token = token_for(url, environ)
    if not token and not dry_run:
        raise RemoteError(
            [f"no token for {url}: make one on its Tokens page, then nest login --registry {url}"]
        )
    with tempfile.TemporaryDirectory() as tmp:
        files = build(project, Path(tmp))
        wheel = next(f for f in files if f.suffix == ".whl")
        if not host:
            pkg = Path(entry.manifest.root).name
            if f"{pkg}/module.yml" not in zipfile.ZipFile(wheel).namelist():
                raise RemoteError([f"{wheel.name} does not carry {pkg}/module.yml"])
        else:
            files = [wheel]  # the index takes the host's wheel (its source is the repository)
        say(f"{entry.name if entry else dist} {version}: " + ", ".join(f.name for f in files))
        if dry_run:
            return []
        from nest.signing import fingerprint, public_of, sign, signing_key  # noqa: PLC0415

        key = signing_key(environ)
        public = public_of(key) if key else ""
        say(f"signed by {fingerprint(public)}" if key else "unsigned (nest keygen makes a key)")
        done = []
        with _client(url, token) as c:
            for f in files:
                data = f.read_bytes()
                fields = {"visibility": "private" if private else "public"}
                if key:
                    sha = hashlib.sha256(data).hexdigest()
                    fields.update(signature=sign(key, f.name, sha), key=public)
                r = c.post(
                    "/api/v1/upload",
                    files={"file": (f.name, data, "application/octet-stream")},
                    data=fields,
                )
                if r.status_code != 201:
                    raise RemoteError([f"{url} refused {f.name}: {_detail(r)}"])
                done.append(r.json())
                say(f"published {f.name}")
    return done


# --- what it offers ----------------------------------------------------------------------------


def catalog(
    url: str | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    core: str | None = None,
    q: str = "",
) -> list[dict[str, Any]]:
    """The registry's packages, each with its newest release (that works with nest-core
    ``core``, when given), or RemoteError."""
    url = (url or registry_url(environ)).rstrip("/")
    params = {k: v for k, v in (("nest", core or ""), ("q", q)) if v}
    try:
        with _client(url, token_for(url, environ)) as c:
            r = c.get("/api/v1/packages", params=params)
    except Exception as e:  # noqa: BLE001
        raise RemoteError([f"{url} does not answer: {e}"]) from None
    if r.status_code != 200:
        raise RemoteError([f"{url}: {_detail(r)}"])
    return list(r.json().get("packages") or [])


def index_projects(url: str | None = None, environ: Mapping[str, str] | None = None) -> set[str]:
    """Every distribution the registry's index has (nest-core among them, when published)."""
    url = (url or registry_url(environ)).rstrip("/")
    try:
        with _client(url, token_for(url, environ)) as c:
            r = c.get("/simple/", headers={"Accept": "application/vnd.pypi.simple.v1+json"})
        return {p["name"] for p in r.json().get("projects", [])} if r.status_code == 200 else set()
    except Exception:  # noqa: BLE001
        return set()


def published(url: str, dist: str, version: str, environ: Mapping[str, str] | None = None) -> bool:
    """Whether the registry's index has this version of a distribution already."""
    from packaging.utils import canonicalize_name  # noqa: PLC0415

    try:
        with _client(url, token_for(url, environ)) as c:
            r = c.get(
                f"/simple/{canonicalize_name(dist)}/",
                headers={"Accept": "application/vnd.pypi.simple.v1+json"},
            )
    except Exception as e:  # noqa: BLE001
        raise RemoteError([f"{url} does not answer: {e}"]) from None
    if r.status_code == 404:
        return False
    if r.status_code != 200:
        raise RemoteError([f"{url}: {_detail(r)}"])
    return version in (r.json().get("versions") or [])


def projects_in(roots: list[Path]) -> list[Path]:
    """Every package project under ``roots``, the host first, then in folder order."""
    found = []
    for root in roots:
        candidates = (
            [root] if (root / "pyproject.toml").is_file() else sorted(root.rglob("pyproject.toml"))
        )
        for project in candidates:
            folder = project if project.is_dir() else project.parent
            if ".venv" in folder.parts or "applications" in folder.parts:
                continue
            if (folder / "src").is_dir():
                found.append(folder)
    found = list(dict.fromkeys(found))
    found.sort(key=lambda p: (_dist_of(p)[0] not in INDEX_ONLY,))
    return found


def publish_all(
    roots: list[Path],
    url: str | None = None,
    *,
    dry_run: bool = False,
    say: Callable[[str], None] = print,
    environ: Mapping[str, str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Publish every package under ``roots`` whose version the registry lacks: (published,
    already there, refused). For CI: run on a tag, it publishes what the tag changed."""
    url = (url or registry_url(environ)).rstrip("/")
    done, there, refused = [], [], []
    for project in projects_in(roots):
        dist, version = _dist_of(project)
        if published(url, dist, version, environ):
            there.append(f"{dist} {version}")
            continue
        try:
            publish(project, url, dry_run=dry_run, say=say, environ=environ)
            done.append(f"{dist} {version}")
        except RemoteError as e:
            refused.append(f"{dist} {version}: " + "; ".join(e.problems))
    return done, there, refused


def _post(
    url: str, path: str, body: dict[str, Any], environ: Mapping[str, str] | None
) -> dict[str, Any]:
    token = token_for(url, environ)
    if not token:
        raise RemoteError([f"no token for {url}: nest login --registry {url}"])
    try:
        with _client(url, token) as c:
            r = c.post(path, json=body)
    except Exception as e:  # noqa: BLE001
        raise RemoteError([f"{url} does not answer: {e}"]) from None
    if r.status_code not in (200, 201):
        raise RemoteError([f"{url}: {_detail(r)}"])
    return r.json()


def register_key(
    public: str, name: str, url: str | None = None, environ: Mapping[str, str] | None = None
) -> str:
    url = (url or registry_url(environ)).rstrip("/")
    return str(_post(url, "/api/v1/keys", {"public": public, "name": name}, environ)["fingerprint"])


def set_visibility(
    name: str, visibility: str, url: str | None = None, environ: Mapping[str, str] | None = None
) -> None:
    url = (url or registry_url(environ)).rstrip("/")
    _post(url, f"/api/v1/packages/{name}/visibility", {"visibility": visibility}, environ)


def yank(
    name: str, version: str, reason: str = "", *, undo: bool = False,
    url: str | None = None, environ: Mapping[str, str] | None = None,
) -> None:  # fmt: skip
    url = (url or registry_url(environ)).rstrip("/")
    _post(url, f"/api/v1/packages/{name}/{version}/yank", {"reason": reason, "undo": undo}, environ)


def package(
    name: str, url: str | None = None, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """One package's page in the catalog: its releases and files (with their signatures)."""
    url = (url or registry_url(environ)).rstrip("/")
    try:
        with _client(url, token_for(url, environ)) as c:
            r = c.get(f"/api/v1/packages/{name}")
    except Exception as e:  # noqa: BLE001
        raise RemoteError([f"{url} does not answer: {e}"]) from None
    if r.status_code != 200:
        raise RemoteError([f"{url}: {name}: {_detail(r)}"])
    return r.json()
