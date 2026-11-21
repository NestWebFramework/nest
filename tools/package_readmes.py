"""Write the README of every Nest package from its manifest (module.yml): its name, what
it does, its version, the Nest versions it works with, how an application uses it, its
settings, and where its reference page is. A README that exists is brought up to date
between the markers it carries; one without them is left alone (tests/test_versions.py
still checks it states the right version).

    uv run python tools/package_readmes.py          # every package of the workspace
    uv run python tools/package_readmes.py --check  # say which READMEs are out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = "https://nest-framework.org/docs/reference"
KINDS = {"module": "modules", "theme": "themes", "provider": "providers", "interface": "interfaces"}
START, END = "<!-- nest:readme -->", "<!-- /nest:readme -->"


def manifests() -> list[Path]:
    return sorted(p for p in ROOT.glob("**/src/*/module.yml") if ".venv" not in p.parts)


def block(manifest: Path) -> tuple[Path, str]:
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    info = raw.get("module") or {}
    name, kind = info.get("name", ""), info.get("type", "")
    pkg = manifest.parents[2]
    dist = ""
    pyproject = pkg / "pyproject.toml"
    if pyproject.is_file():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.startswith("name = "):
                dist = line.split("=", 1)[1].strip().strip('"')
                break
    title = info.get("title") or name
    desc = " ".join(str(info.get("description") or "").split())
    lines = [f"# {title}", ""]
    if desc:
        lines += [desc, ""]
    facts = [f"**Version {info.get('version', '?')}**", kind]
    if raw.get("nest"):
        facts.append(f"works with Nest `{raw['nest']}`")
    if info.get("license"):
        facts.append(f"licence {info['license']}")
    lines += [" · ".join(facts), ""]
    lines += [
        "| | |",
        "|---|---|",
        f"| package | `{dist or name}` |",
        f"| name in a manifest | `{name}` |",
    ]
    if info.get("category"):
        lines.append(f"| category | {info['category']} |")
    if kind in KINDS:
        lines.append(f"| reference | {DOCS}/{KINDS[kind]}/{name} |")
    lines.append("")
    lines += ["## Using it", ""]
    if kind == "module":
        lines += [
            "In an application's `module.yml`:",
            "",
            "```yaml",
            "modules:",
            f"  - name: {name}",
            "    route: /" + name if raw.get("main") else f"  - name: {name}",
            "```",
            "",
        ]
    elif kind == "theme":
        lines += [
            "In an application's `module.yml`:",
            "",
            "```yaml",
            "application:",
            f"  theme: {name}",
            "```",
            "",
        ]
    elif kind == "provider":
        ifaces = raw.get("implements") or (raw.get("provides") or {}).get("interface") or []
        if isinstance(ifaces, str):
            ifaces = [ifaces]
        target = ifaces[0] if ifaces else "nest.<interface>"
        lines += [
            "Bound by an application to the interface it implements:",
            "",
            "```yaml",
            "bind:",
            f"  {target}:",
            f"    providers: [{name}]",
            "```",
            "",
        ]
    elif kind == "interface":
        lines += [
            f"A module asks for it in its manifest (`requires: interfaces: [{name}]`); the application binds a provider to it.",
            "",
        ]
    else:
        lines += ["Part of a Nest application's plan; see its reference page.", ""]
    settings = raw.get("settings") or {}
    if settings:
        lines += ["## Settings", "", "| setting | kind | default |", "|---|---|---|"]
        for key, spec in settings.items():
            spec = spec or {}
            default = (
                "*(secret)*"
                if spec.get("secret")
                else f"`{spec.get('default', '')}`"
                if spec.get("default", "") != ""
                else ""
            )
            lines.append(f"| `{key}` | {spec.get('type', '')} | {default} |")
        lines += ["", "What each does: the reference page, or the admin panel's Settings."]
    return pkg / "README.md", "\n".join(lines).rstrip() + "\n"


def core() -> tuple[Path, str]:
    pyproject = (ROOT / "packages/nest-core/pyproject.toml").read_text(encoding="utf-8")
    version = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in pyproject.splitlines()
        if line.startswith("version = ")
    )
    text = (
        "# nest-core\n\n"
        "The host: manifests, the catalog and the plan, bindings, the module host, security,\n"
        "templates and languages, `nest` (the command line), `nest run` and `nest serve`.\n\n"
        f"**Version {version}** · Nest's own version (this package's is the one place it is written;\n"
        "`nest --version` says it) · licence MIT\n\n"
        "Documentation: https://nest-framework.org/docs/\n"
    )
    return ROOT / "packages/nest-core/README.md", text


def write(path: Path, generated: str, check: bool) -> bool:
    """Whether it was (or, checking, would be) changed."""
    wrapped = f"{START}\n{generated}{END}\n"
    if path.is_file():
        current = path.read_text(encoding="utf-8")
        if START not in current:
            return False  # written by hand: left alone
        head, _, rest = current.partition(START)
        _, _, tail = rest.partition(END)
        new = head + wrapped + tail.lstrip("\n")
    else:
        current, new = "", wrapped
    if new == current:
        return False
    if not check:
        path.write_text(new, encoding="utf-8")
    return True


def main() -> int:
    check = "--check" in sys.argv
    changed = []
    for path, text in [core(), *(block(m) for m in manifests())]:
        if write(path, text, check):
            changed.append(path.relative_to(ROOT))
    for p in changed:
        print(("out of date: " if check else "written: ") + str(p))
    print(f"{len(changed)} README(s) {'out of date' if check else 'written'}")
    return 1 if check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
