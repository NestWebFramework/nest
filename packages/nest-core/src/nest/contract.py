"""Contracts: what a package of each type must and must not declare.

The idea is Rho's ``modulecontract``: the validator does not carry an
ecosystem's types. Each ecosystem publishes a contract (YAML) through the
``nest.contracts`` entry point; contracts are merged, a later one refining an
earlier one, and every manifest is checked against the rule for its type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import yaml

from nest.manifest import Manifest

CORE_CONTRACT = Path(__file__).parent / "contracts" / "core.v1.yml"


@dataclass
class TypeRule:
    description: str = ""
    required: list[str] = field(default_factory=list)
    forbidden: dict[str, str] = field(default_factory=dict)
    ecosystem: str = "nest"


@dataclass
class Contract:
    types: dict[str, TypeRule] = field(default_factory=dict)
    ecosystems: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any], source: str) -> Contract:
        if not isinstance(raw, dict) or not isinstance(raw.get("types"), dict):
            raise ValueError(f"{source}: a contract has a 'types' mapping")
        ecosystem = str(raw.get("ecosystem", "unknown"))
        types: dict[str, TypeRule] = {}
        for name, rule in raw["types"].items():
            rule = rule or {}
            forbidden = rule.get("forbidden") or {}
            if isinstance(forbidden, list):
                forbidden = {key: "not allowed for this type" for key in forbidden}
            types[str(name)] = TypeRule(
                description=str(rule.get("description", "")),
                required=[str(r) for r in rule.get("required") or []],
                forbidden={str(k): str(v) for k, v in forbidden.items()},
                ecosystem=ecosystem,
            )
        return cls(types=types, ecosystems=[ecosystem])

    @classmethod
    def load(cls, path: Path) -> Contract:
        return cls.from_mapping(yaml.safe_load(Path(path).read_text(encoding="utf-8")), str(path))

    def merge(self, other: Contract) -> None:
        """Add another contract's types. A type declared twice is the later one."""
        self.types.update(other.types)
        self.ecosystems.extend(e for e in other.ecosystems if e not in self.ecosystems)

    def validate(self, manifest: Manifest) -> list[str]:
        """Every way ``manifest`` breaks the rule for its type, or an empty list."""
        rule = self.types.get(manifest.type)
        if rule is None:
            known = ", ".join(sorted(self.types))
            return [f"type '{manifest.type}' is not known (known: {known})"]
        problems = []
        for section in rule.required:
            if not _present(manifest.raw, section):
                problems.append(f"a {manifest.type} must declare '{section}'")
        for section, reason in rule.forbidden.items():
            if _present(manifest.raw, section):
                problems.append(f"a {manifest.type} must not declare '{section}': {reason}")
        return problems


def _present(raw: dict[str, Any], dotted: str) -> bool:
    node: Any = raw
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return node not in (None, "", [], {})


def load_contracts() -> Contract:
    """The core contract, then every contract an installed ecosystem publishes."""
    contract = Contract.load(CORE_CONTRACT)
    for ep in sorted(entry_points(group="nest.contracts"), key=lambda e: e.name):
        if ep.name == "core":
            continue
        contract.merge(Contract.load(Path(ep.load())))
    return contract
