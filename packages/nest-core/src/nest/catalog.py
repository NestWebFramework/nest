"""The catalog: every package Nest can see, by name, by id and by former id.

Packages are found two ways, as RoboHub finds its modules by a discovery glob:

* installed Python packages that declare a ``nest.modules`` entry point (the
  manifest sits inside the package, so it ships with the wheel);
* an application's own folder, ``<app>/modules/*/module.yml``, for code that
  belongs to one application only.

Discovery reads manifests; it imports nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from importlib.util import find_spec
from pathlib import Path

from nest.manifest import MANIFEST_FILE, Manifest, ManifestError, load_manifest


@dataclass(frozen=True)
class Entry:
    manifest: Manifest
    source: str  # "package", "local" or "application"
    package: str | None = None

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def type(self) -> str:
        return self.manifest.type

    @property
    def root(self) -> Path:
        return self.manifest.root


class Catalog:
    def __init__(self) -> None:
        self._by_name: dict[str, Entry] = {}
        self._by_id: dict[str, Entry] = {}
        self._aliases: dict[str, Entry] = {}
        self.problems: list[str] = []
        # Names claimed by more than one package. A plan that uses one stops:
        # silently taking either would run code nobody chose.
        self.conflicts: dict[str, list[str]] = {}

    def __iter__(self):
        return iter(sorted(self._by_name.values(), key=lambda e: e.name))

    def __len__(self) -> int:
        return len(self._by_name)

    def add(self, entry: Entry) -> None:
        name, id_ = entry.name, entry.id
        if name in self._by_name:
            other = self._by_name[name]
            self.conflicts.setdefault(name, [other.manifest.source]).append(entry.manifest.source)
            self.problems.append(
                f"two packages are named '{name}': {other.manifest.source} and "
                f"{entry.manifest.source}; the first is used"
            )
            return
        if id_ in self._by_id:
            self.problems.append(f"two packages have the id '{id_}'")
            return
        self._by_name[name] = entry
        self._by_id[id_] = entry
        for old in entry.manifest.module.previous_ids:
            self._aliases.setdefault(old, entry)

    def find(self, ref: str) -> tuple[Entry | None, str | None]:
        """A package by name or id; a former id finds it too, with a note saying so."""
        if ref in self._by_name:
            return self._by_name[ref], None
        if ref in self._by_id:
            return self._by_id[ref], None
        if ref in self._aliases:
            entry = self._aliases[ref]
            return entry, f"'{ref}' is a former id of '{entry.id}'; use the new id"
        return None, None

    def of_type(self, type_: str) -> list[Entry]:
        return [e for e in self if e.type == type_]

    def interface(self, name: str) -> Entry | None:
        for entry in self.of_type("interface"):
            spec = entry.manifest.interface
            if spec is not None and spec.name == name:
                return entry
        return None

    @classmethod
    def discover(cls, app_root: Path | None = None) -> Catalog:
        catalog = cls()
        for package, path in _packaged():
            catalog._load(path, "package", package)
        if app_root is not None:
            for path in sorted((Path(app_root) / "modules").glob(f"*/{MANIFEST_FILE}")):
                catalog._load(path, "local", None)
        return catalog

    def _load(self, path: Path, source: str, package: str | None) -> None:
        try:
            manifest = load_manifest(path)
        except ManifestError as e:
            self.problems.append(str(e))
            return
        self.add(Entry(manifest=manifest, source=source, package=package))


def _packaged() -> list[tuple[str, Path]]:
    found = []
    for ep in sorted(entry_points(group="nest.modules"), key=lambda e: e.name):
        package = ep.value.split(":")[0]
        spec = find_spec(package)
        if spec is None or not spec.submodule_search_locations:
            continue
        found.append((package, Path(list(spec.submodule_search_locations)[0]) / MANIFEST_FILE))
    return found
