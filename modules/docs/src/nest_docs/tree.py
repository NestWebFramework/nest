"""The documentation's tree: its sections and pages (site.yml), each page read and
rendered once (again when it changes, with ``reload``), links between pages made the
site's, and the reference pages made from the packages' manifests."""

from __future__ import annotations

import posixpath
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nest_docs.markdown import Page, render

VERSION_TOKEN = "%NEST_VERSION%"


def versioned(source: str) -> str:
    """A page's text with %NEST_VERSION% made Nest's version (the one place it is written is
    nest-core's package): the documentation says which Nest it is for, and never falls behind."""
    if VERSION_TOKEN not in source:
        return source
    from nest import __version__

    return source.replace(VERSION_TOKEN, __version__)


MEDIA = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}


@dataclass
class Entry:
    key: str  # "start/install"
    title: str
    section: str
    file: Path | None = None  # None: made, not read (a reference page)
    made: Any = None  # a function making the page's Markdown


@dataclass
class Section:
    title: str
    entries: list[Entry] = field(default_factory=list)


class Tree:
    def __init__(
        self, root: Path, base: str, *, reload: bool = False, reference: list[Any] | None = None
    ):
        self.root = root.resolve()
        self.base = base.rstrip("/")
        self.reload = reload
        self._lock = threading.Lock()
        self._pages: dict[str, tuple[float, Page]] = {}
        self.reference = reference or []
        self.load()

    # --- the shape -----------------------------------------------------------------

    def load(self) -> None:
        spec_file = self.root / "site.yml"
        spec = yaml.safe_load(spec_file.read_text(encoding="utf-8")) if spec_file.is_file() else {}
        spec = spec or {}
        self.title = str(spec.get("title") or "Documentation")
        self.sections: list[Section] = []
        self.entries: dict[str, Entry] = {}
        for s in spec.get("sections") or []:
            section = Section(str(s.get("title", "")))
            for key in s.get("pages") or []:
                key = str(key).removesuffix(".md")
                file = self.root / f"{key}.md"
                if not file.is_file():
                    continue
                e = Entry(key, self._title_of(file, key), section.title, file)
                section.entries.append(e)
                self.entries[key] = e
            if s.get("reference") and self.reference:
                for ref in self.reference:
                    if ref.kind != s.get("reference"):
                        continue
                    e = Entry(
                        f"reference/{ref.kind}/{ref.name}",
                        ref.title,
                        section.title,
                        None,
                        ref.markdown,
                    )
                    section.entries.append(e)
                    self.entries[e.key] = e
            self.sections.append(section)
        for key in ("index", "landing"):  # the tree's own front and landing pages
            file = self.root / f"{key}.md"
            if file.is_file() and key not in self.entries:
                self.entries[key] = Entry(key, self._title_of(file, key), "", file)

    def _title_of(self, file: Path, key: str) -> str:
        page = render(versioned(file.read_text(encoding="utf-8")))
        return page.title or key.rsplit("/", 1)[-1].replace("-", " ").capitalize()

    # --- pages ---------------------------------------------------------------------

    def url(self, key: str) -> str:
        return f"{self.base}/" if key == "index" else f"{self.base}/{key}"

    def page(self, key: str) -> Page | None:
        e = self.entries.get(key)
        if e is None:
            return None
        if e.file is None:
            return render(e.made(), link=self._linker(key))
        stamp = e.file.stat().st_mtime if self.reload else 0.0
        with self._lock:
            cached = self._pages.get(key)
            if cached and cached[0] == stamp:
                return cached[1]
        page = render(versioned(e.file.read_text(encoding="utf-8")), link=self._linker(key))
        with self._lock:
            self._pages[key] = (stamp, page)
        return page

    def _linker(self, key: str) -> Any:
        """A page's relative links made the site's: other.md → /docs/other, a picture
        beside it → /docs/_files/start/shot.png; addresses elsewhere left as they are."""
        here = posixpath.dirname(key)

        def link(url: str, image: bool = False) -> str:
            if url.startswith(("http://", "https://", "mailto:", "/", "#")):
                return url
            path, _, anchor = url.partition("#")
            target = posixpath.normpath(posixpath.join(here, path)) if path else key
            if image or Path(target).suffix.lower() in MEDIA:
                return f"{self.base}/_files/{target}"
            target = target.removesuffix(".md")
            if target.endswith("/index"):
                target = target[: -len("/index")] or "index"
            return self.url(target) + (f"#{anchor}" if anchor else "")

        return link

    def file(self, path: str) -> Path | None:
        """A picture of the tree, safely: inside it, of a kind a page shows."""
        target = (self.root / path).resolve()
        if (
            not target.is_relative_to(self.root)
            or target.suffix.lower() not in MEDIA
            or not target.is_file()
        ):
            return None
        return target

    def neighbours(self, key: str) -> tuple[Entry | None, Entry | None]:
        flat = [e for s in self.sections for e in s.entries]
        keys = [e.key for e in flat]
        if key not in keys:
            return None, None
        i = keys.index(key)
        return (flat[i - 1] if i > 0 else None), (flat[i + 1] if i + 1 < len(flat) else None)

    def all_pages(self) -> list[tuple[Entry, Page]]:
        out = []
        for key, e in self.entries.items():
            if key == "landing":
                continue
            page = self.page(key)
            if page is not None:
                out.append((e, page))
        return out

    # --- checking ------------------------------------------------------------------

    def broken(self) -> list[str]:
        """Every link to a page or a picture of the tree that is not there."""
        import re

        problems = []
        known = {self.url(k) for k in self.entries}
        for e, page in self.all_pages():
            for href in re.findall(r'(?:href|src)="([^"]+)"', str(page.html)):
                if not href.startswith(self.base + "/"):
                    continue
                path = href.split("#")[0]
                if path.startswith(f"{self.base}/_files/"):
                    if self.file(path[len(self.base) + len("/_files/") :]) is None:
                        problems.append(f"{e.key}: no picture {path}")
                elif path not in known and path.rstrip("/") not in {u.rstrip("/") for u in known}:
                    problems.append(f"{e.key}: no page {path}")
        for s in self.sections:
            if not s.entries:
                problems.append(f"site.yml: section '{s.title}' has no page that exists")
        return problems
