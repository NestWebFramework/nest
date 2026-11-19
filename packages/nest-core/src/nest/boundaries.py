"""Boundaries: a package uses another only as that one's manifest allows.

``nest validate --strict`` reads each package's code (not its tests or migrations) and
reports where it crosses into another package other than by the front door:

* importing another package's internals (``from nest_auth.sessions import ...``) instead
  of its published API (``provides.exports``). A part may use its host's own modules
  (a game subsystem, the engine's ``nest_saga.store``);
* importing a name the other package does not export;
* importing a package it does not depend on (``deps``): at the top of a file that is an
  error; inside a function it is a hidden optional dependency, a warning (ask with a
  lookup, or declare it in ``uses``). A package it only ``uses`` is imported where it is
  used, never at load;
* reading another module's run-time state (``module_state(request, "media")``), or the
  host's private ``_nest``.

What it finds is what would break, or silently change, when the other package is
disabled, uninstalled or upgraded: the reason for the rule.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path

from nest.catalog import Entry

SKIP_DIRS = {"tests", "migrations", "__pycache__", "node_modules", ".venv"}


@dataclass(frozen=True)
class Finding:
    level: str  # error | warning
    package: str
    where: str  # file:line
    message: str

    def __str__(self) -> str:
        mark = "✗" if self.level == "error" else "!"
        return f"{mark} {self.package}: {self.message}  ({self.where})"


def _root(entry: Entry) -> str | None:
    return entry.manifest.provides.import_ or entry.manifest.main


def code_folder(entry: Entry) -> Path | None:
    main = entry.manifest.main
    if not main:
        return None
    if (entry.root / "__init__.py").is_file() and entry.root.name == main:
        return entry.root  # an installed package: its root is its code
    for candidate in (entry.root / "src" / main, entry.root / main):
        if candidate.is_dir():
            return candidate
    single = entry.root / f"{main}.py"
    return single if single.is_file() else None


def _files(folder: Path) -> list[Path]:
    if folder.is_file():
        return [folder]
    return sorted(
        p for p in folder.rglob("*.py") if not SKIP_DIRS & set(p.relative_to(folder).parts[:-1])
    )


def check(entries: list[Entry], known: list[Entry]) -> list[Finding]:
    """The findings for ``entries``, judged against every package in ``known``."""
    roots: dict[str, Entry] = {}
    for e in known:
        root = _root(e)
        if root:
            roots.setdefault(root, e)
    findings: list[Finding] = []
    for entry in entries:
        folder = code_folder(entry)
        if folder is None:
            continue
        mine = _root(entry)
        deps = set(entry.manifest.deps)
        uses = set(entry.manifest.uses)
        for path in _files(folder):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            except SyntaxError as e:
                findings.append(
                    Finding("error", entry.name, f"{path}:{e.lineno}", "cannot be read")
                )
                continue
            findings += _check_file(entry, mine, deps, uses, roots, path, tree)
    for ep in entry_points(group="nest.checks"):  # an ecosystem's own (saga: world state)
        try:
            extra = ep.load()
        except Exception as e:  # noqa: BLE001 - reported, the others still run
            findings.append(Finding("error", ep.name, ep.value, f"its check cannot load: {e}"))
            continue
        findings += extra(entries, known)
    return findings


def _check_file(
    entry: Entry,
    mine: str | None,
    deps: set[str],
    uses: set[str],
    roots: dict[str, Entry],
    path: Path,
    tree: ast.AST,
) -> list[Finding]:
    out: list[Finding] = []
    top_level = {id(n) for n in getattr(tree, "body", [])}
    host = entry.manifest.part_of

    def at(node: ast.AST) -> str:
        return f"{path}:{getattr(node, 'lineno', 0)}"

    def judge(module: str, names: list[str], node: ast.AST) -> None:
        base = module.split(".")[0]
        other = roots.get(base)
        if other is None or base == mine or other.name == entry.name:
            return
        lazy = id(node) not in top_level and not _in_type_checking(tree, node)
        if other.name in uses and other.name not in deps:
            if not lazy:
                out.append(
                    Finding(
                        "error",
                        entry.name,
                        at(node),
                        f"imports {other.name} at load, but only uses it when present: import it where it is used",
                    )
                )
        elif other.name not in deps and other.type not in ("interface",):
            if lazy:
                out.append(
                    Finding(
                        "warning",
                        entry.name,
                        at(node),
                        f"uses {other.name} without depending on it: declare it, or ask with a lookup",
                    )
                )
            else:
                out.append(
                    Finding(
                        "error",
                        entry.name,
                        at(node),
                        f"imports {other.name} without depending on it",
                    )
                )
        if module != base:
            if other.name != host:  # a part may use its host's own modules
                out.append(
                    Finding(
                        "error",
                        entry.name,
                        at(node),
                        f"reaches into {other.name}'s internals ({module}); use what it exports",
                    )
                )
            return
        exports = set(other.manifest.provides.exports)
        if exports and other.name != host:
            for name in names:
                if name != "*" and name not in exports:
                    out.append(
                        Finding(
                            "error",
                            entry.name,
                            at(node),
                            f"uses {other.name}.{name}, which {other.name} does not export",
                        )
                    )

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            judge(node.module, [a.name for a in node.names], node)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                judge(alias.name, [], node)
        elif (
            isinstance(node, ast.Call)
            and _name(node.func) == "module_state"
            and len(node.args) >= 2
        ):
            target = node.args[1]
            if (
                isinstance(target, ast.Constant)
                and isinstance(target.value, str)
                and target.value != entry.name
            ):
                out.append(
                    Finding(
                        "error",
                        entry.name,
                        at(node),
                        f"reads {target.value}'s run-time state; ask it with a lookup instead",
                    )
                )
        elif isinstance(node, ast.Attribute) and node.attr == "_nest":
            out.append(
                Finding(
                    "error", entry.name, at(node), "uses the host's private _nest; use ModuleHost"
                )
            )
    return _dedupe(out)


def _name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _in_type_checking(tree: ast.AST, node: ast.AST) -> bool:
    for top in getattr(tree, "body", []):
        if (
            isinstance(top, ast.If)
            and "TYPE_CHECKING" in ast.unparse(top.test)
            and any(n is node for n in ast.walk(top))
        ):
            return True
    return False


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen, out = set(), []
    for f in findings:
        key = (f.where, f.message)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
