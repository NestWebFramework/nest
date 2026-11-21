"""A reference page for each package installed: what its manifest says (what it does,
its settings with their kinds and defaults, what it needs and provides, its admin page,
its migrations), in Markdown, so the reference is the code's own account of itself."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

KINDS = {"module": "modules", "theme": "themes", "provider": "providers", "interface": "interfaces"}


@dataclass
class Ref:
    kind: str  # "modules", "themes", ...
    name: str
    title: str
    manifest: Any

    def markdown(self) -> str:
        m = self.manifest
        raw = m.raw if hasattr(m, "raw") else {}
        info = raw.get("module", {})
        lines = [f"# {self.title}", ""]
        desc = " ".join(str(info.get("description") or "").split())
        if desc:
            lines += [desc, ""]
        facts = [
            ("Package", f"`{self.name}`"),
            ("Kind", str(info.get("type", ""))),
            ("Version", str(info.get("version", ""))),
            ("Category", str(info.get("category", "") or "")),
            ("Nest", f"`{raw.get('nest', '')}`" if raw.get("nest") else ""),
            ("Licence", str(info.get("license", "") or "")),
        ]
        lines += ["| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in facts if v] + [""]
        req = raw.get("requires") or {}
        needs = list(req.get("interfaces") or [])
        deps = raw.get("deps") or {}
        if needs or deps:
            lines += ["## What it needs", ""]
            if needs:
                lines.append(
                    "Interfaces, bound by the application: "
                    + ", ".join(f"`{x}`" for x in needs)
                    + "."
                )
                lines.append("")
            if deps:
                lines += (
                    ["| Package | Versions |", "|---|---|"]
                    + [f"| `{k}` | `{v}` |" for k, v in deps.items()]
                    + [""]
                )
        if raw.get("implements"):
            lines += [
                "## What it implements",
                "",
                ", ".join(f"`{x}`" for x in raw["implements"])
                + ": an application binds it there (`bind: <interface>: {providers: ["
                + self.name
                + "]}`).",
                "",
            ]
        provides = raw.get("provides") or {}
        if provides.get("interface") or provides.get("exports"):
            lines += ["## What it provides", ""]
            if provides.get("interface"):
                lines.append(f"The interface `{provides['interface']}`.")
            if provides.get("exports"):
                lines.append(
                    "Python: "
                    + ", ".join(f"`{x}`" for x in provides["exports"])
                    + f" from `{provides.get('import', '')}`."
                )
            lines.append("")
        settings = raw.get("settings") or {}
        if settings:
            lines += [
                "## Settings",
                "",
                "Set in the application's `module.yml` (`config:` under the module), in its admin panel,",
                "or from the environment (`NEST_<APP>__"
                + self.name.upper().replace("-", "_")
                + "__<SETTING>`).",
                "",
                "| Setting | Kind | Default | What it does |",
                "|---|---|---|---|",
            ]
            for key, spec in settings.items():
                spec = spec or {}
                kind = spec.get("type", "")
                if spec.get("choices"):
                    kind = f"{kind}: " + " / ".join(str(c) for c in spec["choices"])
                default = (
                    "*(secret)*"
                    if spec.get("secret")
                    else f"`{spec.get('default', '')}`"
                    if spec.get("default", "") != ""
                    else ""
                )
                text = " ".join(
                    str(spec.get("description") or spec.get("label") or "").split()
                ).replace("|", "\\|")
                if spec.get("restart"):
                    text += " *(on restart)*"
                lines.append(f"| `{key}` | {kind} | {default} | {text} |")
            lines.append("")
        admin = raw.get("admin")
        if admin:
            lines += [
                "## In the admin panel",
                "",
                f"**{admin.get('title', '')}**: {admin.get('description', '')}",
                "",
            ]
        if raw.get("db"):
            lines += [
                "## Its tables",
                "",
                "It keeps its own tables and migrations (`nest db upgrade`).",
                "",
            ]
        if raw.get("styles"):
            lines += [
                "## Its look",
                "",
                "Stylesheets: "
                + ", ".join(f"`{s}`" for s in raw["styles"])
                + " (an application restyles it with its own).",
                "",
            ]
        return "\n".join(lines)


def collect(app_root: Any) -> list[Ref]:
    """Every package the application's environment has installed, by kind."""
    from nest.catalog import Catalog

    out = []
    for e in Catalog.discover(app_root):
        raw = e.manifest.raw if hasattr(e.manifest, "raw") else {}
        kind = KINDS.get(str(raw.get("module", {}).get("type", "")))
        if not kind:
            continue
        title = str(raw.get("module", {}).get("title") or e.name)
        out.append(Ref(kind, e.name, title, e.manifest))
    return sorted(out, key=lambda r: (r.kind, r.title.lower()))
