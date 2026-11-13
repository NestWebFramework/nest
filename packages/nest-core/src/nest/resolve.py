"""Resolution: from an application's manifest to the ordered set it runs.

The plan answers, before anything is imported: which packages the application
is made of, in which order they start, which provider answers each interface,
and every reason it cannot run. A plan with problems never starts.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from packaging.specifiers import SpecifierSet

from nest.catalog import Catalog, Entry
from nest.contract import Contract
from nest.manifest import Binding, Instance

# What a host gives the modules it includes, beyond the router, templates and a
# module's own settings, which every module has. A database is not a facility:
# it is the ``nest.db`` interface, bound to an engine provider by the application. A module asks for these under
# ``requires.host``; asking for anything else is an error at plan time, and
# using one it did not ask for is an error at setup.
HOST_FACILITIES = frozenset({"workspace", "realtime"})


class PlanError(Exception):
    def __init__(self, app: str, problems: list[str]):
        self.app = app
        self.problems = problems
        super().__init__(f"application '{app}' cannot run:\n  - " + "\n  - ".join(problems))


@dataclass
class Unit:
    entry: Entry
    instance: Instance | None  # None: included as a dependency, without a route

    @property
    def name(self) -> str:
        return self.entry.name


@dataclass
class Plan:
    app: Entry
    units: list[Unit]
    theme: Entry | None
    bindings: dict[str, Binding]
    interfaces: dict[str, Entry]
    notes: list[str] = field(default_factory=list)

    def unit(self, name: str) -> Unit | None:
        return next((u for u in self.units if u.name == name), None)


def plan(app: Entry, catalog: Catalog, contract: Contract) -> Plan:
    problems: list[str] = []
    notes: list[str] = []
    manifest = app.manifest
    if manifest.type != "application":
        raise PlanError(app.name, [f"'{app.name}' is a {manifest.type}, not an application"])
    problems += [f"{app.name}: {p}" for p in contract.validate(manifest)]

    def conflict(name: str, why: str) -> bool:
        if name in catalog.conflicts:
            sources = " and ".join(catalog.conflicts[name])
            problems.append(f"{why}: two packages are named '{name}' ({sources}); rename one")
            return True
        return False

    def find(ref: str, wanted: set[str], why: str) -> Entry | None:
        if conflict(ref, why):
            return None
        entry, note = catalog.find(ref)
        if note:
            notes.append(note)
        if entry is None:
            problems.append(f"{why}: no package '{ref}' is installed")
            return None
        if entry.type not in wanted:
            kinds = " or ".join(sorted(wanted))
            problems.append(f"{why}: '{ref}' is a {entry.type}, not a {kinds}")
            return None
        return entry

    # 1. The roots: the modules the application mounts, its theme, its providers.
    instances: dict[str, Instance] = {}
    roots: list[Entry] = []
    for inst in manifest.modules:
        if not inst.enabled:
            continue
        entry = find(inst.name, {"module"}, f"{app.name} includes '{inst.name}'")
        if entry is None:
            continue
        if entry.name in instances:
            problems.append(f"{app.name} includes '{entry.name}' twice")
            continue
        instances[entry.name] = inst
        roots.append(entry)

    theme = None
    if manifest.application and manifest.application.theme:
        theme = find(manifest.application.theme, {"theme"}, f"{app.name}'s theme")
        if theme:
            roots.append(theme)

    interfaces: dict[str, Entry] = {}
    for iface, binding in manifest.bind.items():
        iface_entry = catalog.interface(iface)
        if iface_entry is None:
            problems.append(f"{app.name} binds '{iface}', but no installed interface has that name")
            continue
        interfaces[iface] = iface_entry
        roots.append(iface_entry)
        for ref in binding.providers:
            provider = find(ref, {"provider"}, f"{app.name} binds {iface} to '{ref}'")
            if provider is None:
                continue
            if iface not in provider.manifest.implements:
                problems.append(f"'{provider.name}' does not implement {iface}")
            roots.append(provider)
        unknown = set(binding.config) - set(binding.providers)
        for ref in sorted(unknown):
            problems.append(f"{app.name} configures '{ref}' for {iface}, but does not bind it")

    # 2. The closure over dependencies, with each version range checked.
    included: dict[str, Entry] = {}
    edges: dict[str, set[str]] = {}
    queue = list(roots)
    while queue:
        entry = queue.pop()
        if entry.name in included:
            continue
        included[entry.name] = entry
        edges.setdefault(entry.name, set())
        for dep, spec in entry.manifest.deps.items():
            if conflict(dep, f"{entry.name} depends on '{dep}'"):
                continue
            dep_entry, note = catalog.find(dep)
            if note:
                notes.append(note)
            if dep_entry is None:
                problems.append(f"{entry.name} depends on '{dep}', which is not installed")
                continue
            if spec and not SpecifierSet(spec).contains(
                dep_entry.manifest.version, prereleases=True
            ):
                problems.append(
                    f"{entry.name} needs {dep_entry.name} {spec}, "
                    f"but {dep_entry.manifest.module.version} is installed"
                )
            if dep_entry.type == "application":
                problems.append(f"{entry.name} depends on the application '{dep_entry.name}'")
                continue
            edges[entry.name].add(dep_entry.name)
            queue.append(dep_entry)

    # 3. Every included package keeps its contract and asks only for what exists.
    bound = set(manifest.bind)
    for entry in included.values():
        problems += [f"{entry.name}: {p}" for p in contract.validate(entry.manifest)]
        for facility in entry.manifest.requires.host:
            if facility not in HOST_FACILITIES:
                known = ", ".join(sorted(HOST_FACILITIES))
                problems.append(
                    f"{entry.name} requires the host facility '{facility}' (known: {known})"
                )
        for iface in entry.manifest.requires.interfaces:
            if iface not in bound:
                problems.append(
                    f"{entry.name} requires {iface}; bind it in {app.name}'s module.yml"
                )
    for name, inst in instances.items():
        if inst.route is None:
            problems.append(f"{app.name} includes '{name}' without a route")

    order = _order(edges, problems)
    if problems:
        raise PlanError(app.name, problems + [f"note: {n}" for n in notes])
    units = [Unit(entry=included[name], instance=instances.get(name)) for name in order]
    return Plan(
        app=app,
        units=units,
        theme=theme,
        bindings=dict(manifest.bind),
        interfaces=interfaces,
        notes=notes,
    )


def _order(edges: dict[str, set[str]], problems: list[str]) -> list[str]:
    """Dependencies first; among equals, by name, so every start is the same."""
    waiting = {name: set(deps) & edges.keys() for name, deps in edges.items()}
    dependents: dict[str, set[str]] = {name: set() for name in edges}
    for name, deps in waiting.items():
        for dep in deps:
            dependents[dep].add(name)
    ready = [name for name, deps in waiting.items() if not deps]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for dependent in dependents[name]:
            waiting[dependent].discard(name)
            if not waiting[dependent]:
                heapq.heappush(ready, dependent)
    if len(order) != len(edges):
        cycle = sorted(set(edges) - set(order))
        problems.append(f"a dependency cycle joins: {', '.join(cycle)}")
    return order
