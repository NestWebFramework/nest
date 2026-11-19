"""module.yml: reading a manifest into a typed model.

Every package Nest knows is described by one ``module.yml``. The identity
(``module.id``, ``name``, ``type``, ``version``) is the same core RoboHub uses;
the sections after it say what the package gives and what it needs. The model
types the sections the core understands and lets an ecosystem add its own
(a game ``subsystem`` declares ``tick`` and ``sync``); the contract of the
package's type says which sections it must carry and which it must not.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

MANIFEST_FILE = "module.yml"

_DOTTED = re.compile(r"^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$")
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SETTING = re.compile(r"^[a-z][a-z0-9_]*$")


class ManifestError(Exception):
    """A manifest that cannot be read, with every problem found in it."""

    def __init__(self, source: str, problems: list[str]):
        self.source = source
        self.problems = problems
        super().__init__(f"{source}:\n  - " + "\n  - ".join(problems))


class _Section(BaseModel):
    # A typo in a known section is an error, not a silently ignored key.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Identity(BaseModel):
    """Who a package is. Only ``id`` is its identity; ``name`` may repeat elsewhere."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    type: str
    version: str
    title: str | None = None
    description: str | None = None
    category: str | None = None
    previous_ids: list[str] = Field(default_factory=list)
    license: str | None = None
    maintainer: str | None = None
    created: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _DOTTED.match(v):
            raise ValueError("an id is lower-case and dotted, e.g. 'nest.module.glossary'")
        return v

    @field_validator("previous_ids")
    @classmethod
    def _previous(cls, v: list[str]) -> list[str]:
        for old in v:
            if not _DOTTED.match(old):
                raise ValueError(f"previous id '{old}' is not a dotted id")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _NAME.match(v):
            raise ValueError("a name is lower-case letters, digits, '-' and '_'")
        return v

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        try:
            Version(v)
        except InvalidVersion as e:
            raise ValueError(f"'{v}' is not a version (PEP 440 / semver)") from e
        return v


class Provides(_Section):
    """The public API: the import path other code uses and the names it may use."""

    import_: str | None = Field(default=None, alias="import")
    exports: list[str] = Field(default_factory=list)


class Requires(_Section):
    """What a package needs from whoever includes it."""

    host: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)


class SettingSpec(_Section):
    """A setting a module or provider declares, typed so a value is checked at startup."""

    type: Literal["str", "int", "float", "bool"] = "str"
    default: Any = None
    choices: list[Any] | None = None
    required: bool = False
    secret: bool = False
    description: str | None = None
    label: str | None = None  # what the admin panel's settings page calls it
    editable: bool = True  # shown there to change (False: set in module.yml or the environment)
    # read when the module is set up (its routes depend on it): a change made in the admin
    # panel applies when the application is made again (nest serve reloads it at once)
    restart: bool = False


class InterfaceSpec(_Section):
    """An interface: its name, as code and bindings refer to it, and its Protocol."""

    name: str
    protocol: str

    @field_validator("name")
    @classmethod
    def _iface(cls, v: str) -> str:
        if not _DOTTED.match(v):
            raise ValueError("an interface name is dotted, e.g. 'nest.cache'")
        return v

    @field_validator("protocol")
    @classmethod
    def _protocol(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError("a protocol is written 'package.module:ClassName'")
        return v


class Instance(_Section):
    """A module as an application includes it. The host owns all of this."""

    name: str
    route: str | None = None
    enabled: bool = True
    # core: the application cannot run without it; it is never disabled or uninstalled
    # (nor is anything it depends on). The others are managed in the admin panel.
    core: bool = False
    # optional: if its setup fails, the application starts without it (degraded)
    optional: bool = False
    config: dict[str, Any] = Field(default_factory=dict)
    # set by the workspace's choices (nest.composition), not written in module.yml: a
    # module the administrator added that the manifest does not list
    added: bool = False

    @field_validator("route")
    @classmethod
    def _route(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("/"):
            raise ValueError("a route starts with '/'")
        return v.rstrip("/") or "/" if v else v


class Binding(_Section):
    """Which providers answer an interface in this application, and their settings."""

    providers: list[str] = Field(min_length=1)
    config: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Application(_Section):
    """What makes a package an application: it runs, on a port, with a theme."""

    kind: str = "hosted"
    title: str | None = None
    route: str = "/"
    port: int | None = None
    theme: str | None = None
    command: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["en"])
    default_language: str | None = None
    # the languages its admin panel can be read in (empty: the site's)
    admin_languages: list[str] = Field(default_factory=list)
    # whether the site speaks the browser's language before a visitor chooses (False: its
    # default, as a public site wants for search engines); the admin panel always does
    browser_language: bool = True

    @field_validator("port", mode="before")
    @classmethod
    def _port(cls, v: Any) -> Any:
        return int(v) if isinstance(v, str) and v.isdigit() else v


class Serve(_Section):
    """How ``nest serve`` runs an application: gunicorn's master and its workers.

    workers: processes ("auto": the CPUs this process may use); threads: a worker's
    pool for synchronous handlers; timeout: a silent worker is replaced after it;
    graceful_timeout: what a stopping worker has to finish its requests; max_requests:
    a worker is replaced after so many (with jitter), so slow leaks never pile up.
    """

    workers: int | Literal["auto"] = "auto"
    threads: int = 16
    timeout: int = 30
    graceful_timeout: int = 20
    keepalive: int = 5
    max_requests: int = 5000
    max_requests_jitter: int = 500

    @field_validator("workers", "threads", "timeout", "graceful_timeout", "max_requests")
    @classmethod
    def _positive(cls, v: Any) -> Any:
        if v != "auto" and int(v) < 1:
            raise ValueError("must be 1 or more")
        return v


class Deploy(_Section):
    port: int | None = None
    service: str | None = None
    calls: list[str] = Field(default_factory=list)


class Locale(_Section):
    locale: str
    file: str


class Subsystems(_Section):
    """A module that is the host of parts: an engine and its subsystems, a module and its
    extensions. The parts come as packages of their own, each naming it in ``part_of``."""

    types: list[str] = Field(default_factory=lambda: ["subsystem"])  # what its parts are
    bundled: list[str] = Field(default_factory=list)  # the parts that come with it, by name


class Manifest(BaseModel):
    """A whole module.yml. Unknown top-level sections are kept for the contract to judge."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    module: Identity
    main: str | None = None
    provides: Provides = Field(default_factory=Provides)
    requires: Requires = Field(default_factory=Requires)
    deps: dict[str, str] = Field(default_factory=dict)
    implements: list[str] = Field(default_factory=list)
    interface: InterfaceSpec | None = None
    settings: dict[str, SettingSpec] = Field(default_factory=dict)
    templates: str | None = None
    static: str | None = None
    # Its stylesheets, in its static folder: a module's base look for its own markup, built on
    # the theme's tokens; an application's own, loaded last so it can restyle any module.
    styles: list[str] = Field(default_factory=list)
    # stylesheets for the admin panel only (its pages, the editors' fields)
    admin_styles: list[str] = Field(default_factory=list)
    locales: list[Locale] = Field(default_factory=list)
    application: Application | None = None
    modules: list[Instance] = Field(default_factory=list)
    bind: dict[str, Binding] = Field(default_factory=dict)
    deploy: Deploy | None = None
    serve: Serve | None = None
    # a module whose state lives in its process (a game engine's worlds, kept in
    # memory and ticked there): the application runs as one process while it has it
    one_process: bool = False
    # a provider whose values live in each process (cache-memory): with several workers
    # each has its own, so what must be shared (sign-in limits) looks elsewhere
    process_local: bool = False
    # The parts it hosts (an engine's subsystems), and the host a part belongs to: a part
    # names its host, so one made later, elsewhere, joins it the same way.
    subsystems: Subsystems | None = None
    part_of: str | None = None
    docs: dict[str, Any] = Field(default_factory=dict)
    system_deps: dict[str, Any] = Field(default_factory=dict)
    # Called as fn(nest) once bindings exist and before any module is set up,
    # for packages that prepare the application (the db interface migrates).
    startup: str | None = None
    # Called as fn(nest, entry) for every package uninstalled from the application, by
    # the packages that keep data for others (the db interface drops its tables).
    forget: str | None = None

    @field_validator("startup", "forget")
    @classmethod
    def _startup(cls, v: str | None) -> str | None:
        if v is not None and ":" not in v:
            raise ValueError("a hook is written 'package.module:function'")
        return v

    _root: Path = PrivateAttr(default=Path("."))
    _raw: dict[str, Any] = PrivateAttr(default_factory=dict)
    _source: str = PrivateAttr(default="<memory>")

    # deps grouped by ecosystem, as RoboHub's are: `nest: {auth: ">=0.3,<1"}`, `saga: {farm:
    # ">=0.1,<0.2"}`. They are flattened into deps for the plan; which ecosystem each was
    # listed under is kept here, so the plan can check it is that ecosystem's.
    dep_ecosystems: dict[str, str] = Field(default_factory=dict, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _grouped_deps(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("deps"), dict):
            return data
        flat: dict[str, Any] = {}
        where: dict[str, str] = {}
        for key, value in data["deps"].items():
            if isinstance(value, dict):  # an ecosystem's group
                if not _NAME.match(str(key)):
                    raise ValueError(f"deps: '{key}' is no ecosystem name")
                for name, spec in value.items():
                    if name in flat:
                        raise ValueError(f"deps: '{name}' is listed twice")
                    flat[name] = spec
                    where[str(name)] = str(key)
            else:
                if key in flat:
                    raise ValueError(f"deps: '{key}' is listed twice")
                flat[key] = value
        return {**data, "deps": flat, "dep_ecosystems": where}

    @field_validator("deps")
    @classmethod
    def _deps(cls, v: dict[str, str]) -> dict[str, str]:
        for name, spec in v.items():
            spec = "" if spec in (None, "*") else str(spec)
            try:
                SpecifierSet(spec)
            except InvalidSpecifier as e:
                raise ValueError(f"dependency '{name}': '{spec}' is not a version range") from e
        return {k: ("" if s in (None, "*") else str(s)) for k, s in v.items()}

    @field_validator("settings")
    @classmethod
    def _settings(cls, v: dict[str, SettingSpec]) -> dict[str, SettingSpec]:
        for key, spec in v.items():
            if not _SETTING.match(key):
                raise ValueError(f"setting '{key}' must be snake_case")
            if spec.secret and spec.default is not None:
                raise ValueError(f"setting '{key}' is secret and cannot have a default")
        return v

    @property
    def root(self) -> Path:
        """The folder the manifest lives in; relative paths in it start here."""
        return self._root

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    @property
    def source(self) -> str:
        return self._source

    @property
    def name(self) -> str:
        return self.module.name

    @property
    def id(self) -> str:
        return self.module.id

    @property
    def type(self) -> str:
        return self.module.type

    @property
    def version(self) -> Version:
        return Version(self.module.version)

    def folder(self, declared: str | None, convention: str) -> Path | None:
        """A folder the manifest names, or the conventional one when it exists."""
        path = self._root / (declared or convention)
        if declared is not None and not path.is_dir():
            return None
        return path if path.is_dir() else None


def _describe(err: dict[str, Any]) -> str:
    where = ".".join(str(p) for p in err.get("loc", ()))
    msg = err.get("msg", "invalid")
    msg = msg.removeprefix("Value error, ")
    return f"{where}: {msg}" if where else msg


def parse_manifest(raw: Any, source: str, root: Path) -> Manifest:
    """Validate an already-loaded mapping as a manifest."""
    if not isinstance(raw, dict):
        raise ManifestError(source, ["a manifest is a YAML mapping"])
    try:
        manifest = Manifest.model_validate(raw)
    except ValidationError as e:
        raise ManifestError(source, [_describe(err) for err in e.errors()]) from None
    manifest._root = root
    manifest._raw = raw
    manifest._source = source
    return manifest


def load_manifest(path: Path) -> Manifest:
    """Read ``module.yml`` at ``path`` (a file, or a folder that holds one)."""
    path = Path(path)
    if path.is_dir():
        path = path / MANIFEST_FILE
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError(str(path), ["no such file"]) from None
    except yaml.YAMLError as e:
        raise ManifestError(str(path), [f"not valid YAML: {e}"]) from None
    return parse_manifest(raw, str(path), package_root(path.parent.resolve(), raw))


def package_root(folder: Path, raw: Any) -> Path:
    """Where a manifest's relative paths start. A package keeps its module.yml beside its
    pyproject.toml (one for Nest, one for Python); its templates, migrations and data are
    in its Python package, src/<package>/ (the one it names in main or provides.import, or
    the only one there). An application's or a local module's folder is its own root."""
    src = folder / "src"
    if not ((folder / "pyproject.toml").is_file() and src.is_dir()):
        return folder
    named = []
    if isinstance(raw, dict):
        provides = raw.get("provides") if isinstance(raw.get("provides"), dict) else {}
        named = [
            str(x).split(":")[0].split(".")[0]
            for x in (raw.get("main"), provides.get("import"))
            if x
        ]
    for name in named:
        if (src / name).is_dir():
            return src / name
    packages = [d for d in src.iterdir() if d.is_dir() and (d / "__init__.py").is_file()]
    return packages[0] if len(packages) == 1 else folder
