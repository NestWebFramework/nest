"""Bindings: interfaces answered by providers, with typed, checked settings.

An application names, per interface, the providers that answer it. At startup
each provider's settings are built from its declared specs, the values the
application writes and the environment; a secret is accepted from the
environment only. The object the provider creates is checked against the
interface's Protocol: every method present, async where the interface is
async, with the same parameter names. Nothing is looked up per call.
"""

from __future__ import annotations

import inspect
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, Request
from pydantic import BaseModel, SecretStr, ValidationError, create_model

from nest.catalog import Entry
from nest.loader import import_main, import_object
from nest.manifest import SettingSpec

_TYPES: dict[str, type] = {"str": str, "int": int, "float": float, "bool": bool}


class BindError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("bindings are wrong:\n  - " + "\n  - ".join(problems))


@dataclass(frozen=True)
class ProviderContext:
    """What a provider may know about the application it serves.

    A provider's ``create(settings, context)`` receives this: the application's
    name (for an application_name on a database connection, a key prefix in a
    cache) and its workspace (for a SQLite file or a local media root).
    """

    app: str
    workspace: Path
    production: bool = False

    def path(self, value: str) -> Path:
        """A path a setting names, relative to the workspace unless absolute."""
        p = Path(value).expanduser()
        return p if p.is_absolute() else self.workspace / p


def env_name(app: str, owner: str, key: str) -> str:
    """``NEST_<APP>__<OWNER>__<KEY>``: where a setting is read from the environment."""

    def norm(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "_", s).upper()

    return f"NEST_{norm(app)}__{norm(owner)}__{norm(key)}"


def settings_model(owner: str, specs: Mapping[str, SettingSpec]) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for key, spec in specs.items():
        kind: Any = SecretStr if spec.secret else _TYPES[spec.type]
        if spec.choices:
            kind = Literal[tuple(spec.choices)]
        if spec.required:
            fields[key] = (kind, ...)
        else:
            fields[key] = (kind | None, spec.default)
    safe = re.sub(r"[^A-Za-z0-9]", "_", owner).title().replace("_", "")
    return create_model(f"{safe}Settings", **fields)


def build_settings(
    app: str,
    owner: str,
    specs: Mapping[str, SettingSpec],
    written: Mapping[str, Any],
    environ: Mapping[str, str],
) -> tuple[BaseModel | None, list[str]]:
    problems = []
    for key in written:
        if key not in specs:
            problems.append(
                f"{owner} has no setting '{key}' (declared: {', '.join(specs) or 'none'})"
            )
        elif specs[key].secret:
            problems.append(
                f"{owner}.{key} is secret; set it in the environment as "
                f"{env_name(app, owner, key)}, never in module.yml"
            )
    values = {k: v for k, v in written.items() if k in specs and not specs[k].secret}
    for key in specs:
        var = env_name(app, owner, key)
        if var in environ:
            values[key] = environ[var]
    if problems:
        return None, problems
    try:
        return settings_model(owner, specs).model_validate(values), []
    except ValidationError as e:
        for err in e.errors():
            key = ".".join(str(p) for p in err["loc"])
            hint = f" (or set {env_name(app, owner, key)})" if err["type"] == "missing" else ""
            problems.append(f"{owner}.{key}: {err['msg']}{hint}")
        return None, problems


def conformance(protocol: type, impl: Any, label: str) -> list[str]:
    """How ``impl`` fails to provide what ``protocol`` declares."""
    problems = []
    for name, member in vars(protocol).items():
        if name.startswith("_") or not callable(member):
            continue
        actual = getattr(impl, name, None)
        if actual is None or not callable(actual):
            problems.append(f"{label} does not provide {protocol.__name__}.{name}()")
            continue
        if inspect.iscoroutinefunction(member) != inspect.iscoroutinefunction(actual):
            want = "async" if inspect.iscoroutinefunction(member) else "sync"
            problems.append(f"{label}.{name}() must be {want}, as {protocol.__name__} declares")
        want_params = [p for p in inspect.signature(member).parameters if p != "self"]
        got_params = list(inspect.signature(actual).parameters)
        if want_params != got_params:
            problems.append(
                f"{label}.{name}({', '.join(got_params)}) does not match "
                f"{protocol.__name__}.{name}({', '.join(want_params)})"
            )
    return problems


@dataclass
class BoundProvider:
    name: str
    impl: Any
    settings: BaseModel | None


@dataclass
class Bindings:
    by_interface: dict[str, list[BoundProvider]] = field(default_factory=dict)
    protocols: dict[type, str] = field(default_factory=dict)

    def _key(self, key: str | type) -> str:
        if isinstance(key, str):
            return key
        if key in self.protocols:
            return self.protocols[key]
        raise LookupError(f"{getattr(key, '__name__', key)} is not bound in this application")

    def get(self, key: str | type) -> Any:
        """The first provider bound to an interface, by name or by Protocol."""
        providers = self.by_interface.get(self._key(key))
        if not providers:
            raise LookupError(f"{key} is not bound in this application")
        return providers[0].impl

    def all(self, key: str | type) -> list[Any]:
        return [p.impl for p in self.by_interface.get(self._key(key), [])]

    def providers(self) -> list[BoundProvider]:
        return [p for ps in self.by_interface.values() for p in ps]


def build(
    plan: Any,
    environ: Mapping[str, str] | None = None,
    context: ProviderContext | None = None,
) -> Bindings:
    environ = os.environ if environ is None else environ
    app = plan.app.name
    context = context or ProviderContext(app=app, workspace=Path.cwd())
    problems: list[str] = []
    bindings = Bindings()
    for iface, binding in plan.bindings.items():
        iface_entry: Entry = plan.interfaces[iface]
        spec = iface_entry.manifest.interface
        try:
            protocol = import_object(spec.protocol, iface_entry)
        except Exception as e:  # noqa: BLE001 - reported, then startup stops
            problems.append(f"{iface}: cannot import its protocol {spec.protocol}: {e}")
            continue
        bindings.protocols[protocol] = iface
        for ref in binding.providers:
            unit = plan.unit(ref) or next(
                (
                    u
                    for u in plan.units
                    if ref in (u.entry.id, *u.entry.manifest.module.previous_ids)
                ),
                None,
            )
            entry = unit.entry
            settings, errs = build_settings(
                app, entry.name, entry.manifest.settings, binding.config.get(ref, {}), environ
            )
            if errs:
                problems += errs
                continue
            module = import_main(entry)
            create = getattr(module, "create", None)
            if not callable(create):
                problems.append(f"{entry.name}: its main module has no create(settings, context)")
                continue
            try:
                impl = create(settings, context)
            except Exception as e:  # noqa: BLE001 - reported with the others, then startup stops
                problems.append(f"{entry.name} could not start: {e}")
                continue
            errs = conformance(protocol, impl, entry.name)
            if errs:
                problems += errs
                continue
            bindings.by_interface.setdefault(iface, []).append(
                BoundProvider(name=entry.name, impl=impl, settings=settings)
            )
    if problems:
        raise BindError(problems)
    return bindings


def bound(key: str | type) -> Any:
    """A FastAPI dependency: the provider this application bound to ``key``."""

    def dependency(request: Request) -> Any:
        return request.app.state.nest.bindings.get(key)

    return Depends(dependency)
