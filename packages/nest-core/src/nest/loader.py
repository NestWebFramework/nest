"""Importing a package's code.

An installed package is imported by its name. A package that lives in an
application's folder is imported from its file under a private name, without
touching ``sys.path``, so it can never shadow the standard library or another
package (a FlaskNest component called ``collections`` could).
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import re
import sys
from types import ModuleType
from typing import Any

from nest.catalog import Entry

_cache: dict[str, ModuleType] = {}


class LoadError(Exception):
    pass


def _key(entry: Entry) -> str:
    return entry.id if entry.source == "package" else f"{entry.id}@{entry.root}"


def import_main(entry: Entry) -> ModuleType | None:
    """The package's ``main`` module, or None for a package without code."""
    main = entry.manifest.main
    if not main:
        return None
    key = _key(entry)
    if key in _cache:
        return _cache[key]
    if entry.source == "package":
        module = importlib.import_module(main)
    else:
        module = _import_local(entry, main)
    _cache[key] = module
    return module


def _import_local(entry: Entry, main: str) -> ModuleType:
    path = entry.root / main
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", entry.id)
    # The folder is part of the name: two applications in one process may each
    # have a local module with the same id, and must each get their own.
    digest = hashlib.sha1(str(entry.root).encode()).hexdigest()[:10]
    name = f"_nest_local_{safe}_{digest}"
    if path.is_dir() and (path / "__init__.py").is_file():
        spec = importlib.util.spec_from_file_location(
            name, path / "__init__.py", submodule_search_locations=[str(path)]
        )
    elif path.with_suffix(".py").is_file():
        spec = importlib.util.spec_from_file_location(name, path.with_suffix(".py"))
    else:
        raise LoadError(f"{entry.name}: main '{main}' is neither a package nor a .py file")
    if spec is None or spec.loader is None:
        raise LoadError(f"{entry.name}: cannot import '{main}'")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def import_object(ref: str, entry: Entry) -> Any:
    """``package.module:Attr`` as an object; the package's own main counts as itself."""
    module_part, _, attr = ref.partition(":")
    if entry.source != "package" and module_part == entry.manifest.main:
        module = import_main(entry)
    else:
        module = importlib.import_module(module_part)
    obj: Any = module
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj
