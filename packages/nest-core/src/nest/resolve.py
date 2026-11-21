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


class _Includable:
    """Every type an application may list under modules: whatever is set up, except themes."""

    def __contains__(self, type_: object) -> bool:
        return type_ not in ("interface", "provider", "application", "theme")

    def __iter__(self):  # for the message: "a provider, not a module"
        return iter(["module"])


INCLUDABLE = _Includable()


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
    # the core modules and everything they depend on: never disabled nor uninstalled
    locked: set[str] = field(default_factory=set)
    # the theme, then the one it extends, and so on: templates looked for in this order
    themes: list[Entry] = field(default_factory=list)
    # the modules the application lists but does not run now
    disabled: set[str] = field(default_factory=set)

    def unit(self, name: str) -> Unit | None:
        return next((u for u in self.units if u.name == name), None)


def ecosystem_of(entry: Entry, contract: Contract) -> str:
    """Whose a package is: the ecosystem that defines its type (a subsystem is the game
    engine's), or the one its id names (nest.saga.engine is saga's); else Nest's own."""
    core = contract.ecosystems[0] if contract.ecosystems else "nest"
    rule = contract.types.get(entry.type)
    if rule is not None and rule.ecosystem and rule.ecosystem != core:
        return rule.ecosystem
    for eco in contract.ecosystems:
        if eco != core and entry.id.startswith(f"{core}.{eco}."):
            return eco
    return core


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
    disabled = {inst.name for inst in manifest.modules if not inst.enabled}
    for inst in manifest.modules:
        if inst.core and not inst.enabled:
            problems.append(f"{inst.name} is a core module of {app.name}; it cannot be disabled")
        if not inst.enabled:
            continue
        entry = find(inst.name, INCLUDABLE, f"{app.name} includes '{inst.name}'")
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
        unknown = set(binding.config) - set(binding.providers) - set(binding.alternatives)
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
            if dep_entry.name in disabled:  # never pulled back in behind the administrator
                problems.append(
                    f"{entry.name} needs {dep_entry.name}, which is disabled; "
                    f"enable {dep_entry.name} or disable {entry.name}"
                )
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

    # 2b. An application's own deps are its contract with Nest: each version range is kept
    # by what is installed, and once it declares any, it declares every package it uses
    # (the modules it mounts, its theme, the interfaces it binds and their providers);
    # its own local modules (its folder's modules/) are part of it and need none.
    if manifest.deps:
        for dep, spec in manifest.deps.items():
            dep_entry, _ = catalog.find(dep)
            listed = manifest.dep_ecosystems.get(dep)
            if listed is None:
                problems.append(
                    f"{app.name} depends on '{dep}' without saying whose: list it under its "
                    f"ecosystem (nest: {{{dep}: ...}})"
                )
            if dep_entry is None:
                problems.append(f"{app.name} depends on '{dep}', which is not installed")
                continue
            owner = ecosystem_of(dep_entry, contract)
            if listed is not None and listed != owner:
                problems.append(f"{app.name} lists '{dep}' under {listed}, but it is {owner}'s")
            if spec and not SpecifierSet(spec).contains(
                dep_entry.manifest.version, prereleases=True
            ):
                problems.append(
                    f"{app.name} needs {dep_entry.name} {spec}, "
                    f"but {dep_entry.manifest.module.version} is installed"
                )
        declared = set(manifest.deps)
        added = {i.name for i in manifest.modules if i.added}  # chosen in the workspace
        for entry in roots:
            if entry.source != "local" and entry.name not in declared | added:
                problems.append(
                    f"{app.name} uses '{entry.name}' but its deps give no version range for it"
                )

    # 3. Every included package keeps its contract and asks only for what exists.
    bound = set(manifest.bind)
    core = _core_version()
    for entry in included.values():
        problems += [f"{entry.name}: {p}" for p in contract.validate(entry.manifest)]
        wants = entry.manifest.nest
        if wants and core and not SpecifierSet(wants).contains(core, prereleases=True):
            problems.append(f"{entry.name} works with nest-core {wants}; this is {core}")
        host_name = entry.manifest.part_of
        if host_name:  # a part (an engine's subsystem) joins the host it names
            host = included.get(host_name)
            if host is None:
                problems.append(
                    f"{entry.name} is part of '{host_name}', which {app.name} does not include"
                )
            elif host.manifest.subsystems is None:
                problems.append(f"{entry.name} is part of '{host_name}', which takes no parts")
            elif entry.type not in host.manifest.subsystems.types:
                kinds = ", ".join(host.manifest.subsystems.types)
                problems.append(
                    f"{entry.name} is a {entry.type}, but '{host_name}' takes parts of type {kinds}"
                )
            if host_name not in entry.manifest.deps:
                problems.append(
                    f"{entry.name} is part of '{host_name}' but does not depend on it (deps)"
                )
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
    for entry in [*included.values(), app]:  # a stylesheet it names is in its static folder
        sheets = [*entry.manifest.styles, *entry.manifest.admin_styles]
        if sheets:
            static = entry.manifest.folder(entry.manifest.static, "static")
            for sheet in sheets:
                if static is None or not (static / sheet).is_file():
                    problems.append(
                        f"{entry.name} names the stylesheet '{sheet}', which its static folder lacks"
                    )
    for name, inst in instances.items():
        # A module serves pages, so it needs a route; an ecosystem's part (a game
        # subsystem) may run without one, and so may a module whose pages are all
        # in the admin panel (its manifest has an admin: section), and so may one that
        # serves no pages at all (pages: false, a middleware like the notifications).
        if (
            inst.route is None
            and included.get(name) is not None
            and included[name].type == "module"
            and "admin" not in included[name].manifest.raw
            and included[name].manifest.raw.get("pages", True) is not False
        ):
            problems.append(f"{app.name} includes '{name}' without a route")
        declared = included[name].manifest.settings if name in included else {}
        for key in sorted(set(inst.config) - set(declared)):
            known = ", ".join(declared) or "none"
            problems.append(
                f"{app.name} sets '{key}' for {name}, which has no such setting (settings: {known})"
            )
        for key in sorted(set(inst.config) & set(declared)):
            if declared[key].secret:
                problems.append(
                    f"{app.name} sets {name}.{key}, a secret; set it in the environment instead"
                )

    # an optional partner that is included starts first, unless that would make a cycle
    # (the engine uses its subsystems, which depend on it: that edge is left out)
    ordering = {n: set(e) for n, e in edges.items()}
    for name in sorted(edges):
        for partner in sorted(included[name].manifest.uses):
            if partner in included and partner != name and not _reaches(ordering, partner, name):
                ordering[name].add(partner)
    order = _order(ordering, problems)
    if problems:
        raise PlanError(app.name, problems + [f"note: {n}" for n in notes])
    units = [Unit(entry=included[name], instance=instances.get(name)) for name in order]
    chain: list[Entry] = []
    current = theme
    while current is not None and current not in chain:
        chain.append(current)
        parent = current.manifest.extends
        current = included.get(parent) if parent else None
        if parent and current is None:
            problems.append(f"theme {chain[-1].name} extends '{parent}', which is not installed")
    if problems:
        raise PlanError(app.name, problems + [f"note: {n}" for n in notes])
    locked: set[str] = set()
    stack = [i.name for i in manifest.modules if i.core and i.name in included]
    if theme is not None:
        stack.append(theme.name)  # the theme, and what it needs, are the frame of every page
    while stack:
        name = stack.pop()
        if name not in locked:
            locked.add(name)
            stack += [d for d in edges.get(name, ()) if d not in locked]
    return Plan(
        app=app,
        units=units,
        theme=theme,
        bindings=dict(manifest.bind),
        interfaces=interfaces,
        notes=notes,
        locked=locked,
        disabled=disabled,
        themes=chain,
    )


def _core_version() -> str | None:
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415

    try:
        return version("nest-core")
    except PackageNotFoundError:
        return None


def _reaches(edges: dict[str, set[str]], start: str, goal: str) -> bool:
    """Whether ``goal`` is among what ``start`` (transitively) starts after."""
    seen, stack = set(), [start]
    while stack:
        name = stack.pop()
        if name == goal:
            return True
        if name not in seen:
            seen.add(name)
            stack += edges.get(name, ())
    return False


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
