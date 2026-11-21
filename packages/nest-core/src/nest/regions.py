"""Blocks in a theme's regions: what an administrator places, without code.

A theme says where its pages have room (``regions:`` in its manifest: a sidebar, the
footer, the home page) and shows each with ``{{ region("sidebar") }}``. A module offers
blocks (``offers.blocks``: a template of its own, with settings it asks). The admin panel
(Themes → Regions, or a module's Place it) puts blocks in regions; the choice is the
site's, kept in its workspace:

    data/regions.yml
      sidebar:
        - {module: forum, block: latest, settings: {count: "5"}}
      home:
        - {module: feed, block: readings, settings: {name: settlement}}

A block of a module the site does not run, or that no longer offers it, is skipped; one
whose template fails renders nothing (and is logged), so a page never breaks for a block.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from markupsafe import Markup

log = logging.getLogger("nest.regions")

FILE = Path("data") / "regions.yml"


@dataclass
class Placement:
    module: str
    block: str
    settings: dict[str, str] = field(default_factory=dict)


def load(workspace: Path) -> dict[str, list[Placement]]:
    path = Path(workspace) / FILE
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        log.error("%s is not YAML: no blocks are shown", path)
        return {}
    out: dict[str, list[Placement]] = {}
    for region, items in raw.items() if isinstance(raw, dict) else []:
        for item in items or []:
            if isinstance(item, dict) and item.get("module") and item.get("block"):
                out.setdefault(str(region), []).append(
                    Placement(
                        str(item["module"]),
                        str(item["block"]),
                        {str(k): str(v) for k, v in (item.get("settings") or {}).items()},
                    )
                )
    return out


def save(workspace: Path, placements: dict[str, list[Placement]]) -> None:
    path = Path(workspace) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {r: [asdict(p) for p in items] for r, items in placements.items() if items}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        "# blocks in the theme's regions, chosen in the admin panel (Themes → Regions)\n"
        + yaml.safe_dump(body, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def offered(nest: Any) -> dict[tuple[str, str], Any]:
    """Every block the site's modules offer, by (module, block name)."""
    out = {}
    for unit in nest.plan.units:
        for b in unit.entry.manifest.offers.blocks:
            out[(unit.name, b.name)] = b
    return out


def theme_regions(nest: Any) -> list[Any]:
    """The regions of the theme in use (its own, then those it is built on), by name."""
    out, seen = [], set()
    for theme in nest.plan.themes:
        for r in theme.manifest.regions:
            if r.name not in seen:
                seen.add(r.name)
                out.append((theme.name, r))
    return out


def render(nest: Any, context: Any, name: str) -> Markup:
    """The blocks placed in region ``name``, each in its module's template, given the
    page's context and its settings (``block``)."""
    blocks = offered(nest)
    out = []
    for p in load(nest.workspace).get(name, []):
        offer = blocks.get((p.module, p.block))
        if offer is None:
            continue
        try:
            template = nest.templates.get_template(offer.template)
            values = {
                **context.get_all(),
                "block": p.settings,
                "block_name": f"{p.module}.{p.block}",
            }
            html = template.render(values).strip()
        except Exception:  # noqa: BLE001 - a block never takes a page down
            log.exception("block %s.%s in %s failed", p.module, p.block, name)
            continue
        if html:
            out.append(
                f'<section class="block block-{p.module}-{p.block}" data-region="{name}">{html}</section>'
            )
    return Markup("\n".join(out))
