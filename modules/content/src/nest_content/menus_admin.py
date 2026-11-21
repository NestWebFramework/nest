"""The site's menus in the admin panel (Admin → Content → Menus): made, renamed, deleted;
their items added (a page or an article, a category, a module's pages, any address),
renamed, moved up and down, in and out (an item under another), deleted. Which menus the
theme shows (its menu locations, ``menus:`` in its manifest) is said beside each, and an
item's label in the other languages is a link away (the translations module).

Every change is the site's at once: the menus' cache moves on (service.changed)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser, require_role
from nest_db import Database
from sqlalchemy import func, select

from nest import admin_url, bound, render, translator
from nest.host import module_state
from nest_content import service, translated
from nest_content.models import Entry, Menu, MenuItem, Term

menus = APIRouter()
editor = require_role("editor")


def _here(request: Request) -> str:
    return admin_url(request, "content") + "/menus"


def _registry(request: Request) -> Any:
    return module_state(request, "content")["types"]


def locations(request: Request) -> list[dict[str, str]]:
    """The menus the theme in use shows (its own, then those it is built on): by slug."""
    nest = request.app.state.nest
    out, seen = [], set()
    for theme in nest.plan.themes:
        for loc in theme.manifest.menus:
            if loc.name not in seen:
                seen.add(loc.name)
                out.append({"name": loc.name, "title": loc.title, "theme": theme.name})
    return out


def module_links(request: Request) -> list[dict[str, str]]:
    """The modules of the site that offer a link to their pages (offers.menu), where."""
    nest = request.app.state.nest
    out = []
    for unit in nest.plan.units:
        offer = unit.entry.manifest.offers.menu
        base = nest.module_url(unit.name) if hasattr(nest, "module_url") else None
        if offer is None or not base:
            continue
        path = base.rstrip("/") + "/" + offer.path.lstrip("/")
        out.append(
            {
                "module": unit.name,
                "title": offer.title,
                "url": path.rstrip("/") + "/" if offer.path in ("", "/") else path,
            }
        )
    return out


def _under(column: Any, parent_id: int | None) -> Any:
    """Items under the same parent (none: the menu's top level)."""
    return column.is_(None) if parent_id is None else column == parent_id


def _shown(db: Any, places: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Which menus the theme shows, by slug: its locations, and, when it has a main menu
    and no menu is called main, the site's first menu (which stands in for it)."""
    shown = {p["name"]: p for p in places}
    if "main" in shown:
        with db.session() as s:
            if s.scalar(select(Menu).where(Menu.slug == "main")) is None:
                first = s.scalar(select(Menu).order_by(Menu.id).limit(1))
                if first is not None:
                    shown[first.slug] = shown["main"]
    return shown


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.strip().lower()).strip("-")[:100]


def _items(db: Any, menu_id: int) -> list[tuple[int, Any, str]]:
    """The menu's items in their order, each with its depth and the label it shows."""
    with db.session() as s:
        rows = list(
            s.scalars(
                select(MenuItem)
                .where(MenuItem.menu_id == menu_id)
                .order_by(MenuItem.position, MenuItem.id)
            )
        )
        entries = {
            e.id: e
            for e in s.scalars(
                select(Entry).where(Entry.id.in_([r.entry_id for r in rows if r.entry_id]))
            )
        }
        terms = {
            t.id: t
            for t in s.scalars(
                select(Term).where(Term.id.in_([r.term_id for r in rows if r.term_id]))
            )
        }
    kids: dict[Any, list[Any]] = {}
    for r in rows:
        kids.setdefault(r.parent_id, []).append(r)
    out: list[tuple[int, Any, str]] = []

    def walk(parent: Any, depth: int) -> None:
        for r in kids.get(parent, []):
            target = (
                entries[r.entry_id].path if r.entry_id in entries
                else terms[r.term_id].path if r.term_id in terms
                else r.url
            )  # fmt: skip
            label = r.title or (
                entries[r.entry_id].title if r.entry_id in entries
                else terms[r.term_id].name if r.term_id in terms
                else r.url
            )  # fmt: skip
            r.target = target
            out.append((depth, r, label))
            if depth < 8:
                walk(r.id, depth + 1)

    walk(None, 0)
    return out


def _menu(db: Any, menu_id: int) -> Menu:
    with db.session() as s:
        m = s.get(Menu, menu_id)
    if m is None:
        raise HTTPException(404)
    return m


# --- the menus ----------------------------------------------------------------------------


@menus.get("/menus")
def menus_page(
    request: Request,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
    error: str = "",
):
    with db.session() as s:
        rows = list(s.scalars(select(Menu).order_by(Menu.title)))
        counts = dict(
            s.execute(select(MenuItem.menu_id, func.count()).group_by(MenuItem.menu_id)).all()
        )
    places = locations(request)
    taken = {m.slug for m in rows}
    shown = {p["name"]: p for p in places}
    first = min(rows, key=lambda m: m.id) if rows else None
    if "main" in shown and "main" not in taken and first is not None:
        shown[first.slug] = shown["main"]  # the site's menu of another name stands in
    return render(
        request,
        "content/editor/menus.html",
        rows=rows,
        counts=counts,
        locations=places,
        shown=shown,
        missing=[
            p
            for p in places
            if p["name"] not in taken
            and p["name"] not in ("main",)
            or (p["name"] == "main" and first is None)
        ],
        here=_here(request),
        error=error,
    )


@menus.post("/menus")
def add_menu(
    request: Request,
    title: str = Form(""),
    slug: str = Form(""),
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    t = translator(request)
    title, slug = title.strip()[:200], _slug(slug or title)
    if not title or not slug:
        return menus_page(request, user, db, error=t("A menu needs a name."))
    with db.session() as s:
        if s.scalar(select(Menu).where(Menu.slug == slug)) is not None:
            return menus_page(
                request, user, db, error=t("A menu is called {slug} already.", slug=slug)
            )
    m = service.ensure_menu(db, slug, title)
    return RedirectResponse(f"{_here(request)}/{m.id}", status_code=303)


@menus.get("/menus/{menu_id:int}")
def menu_page(
    request: Request,
    menu_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
    error: str = "",
):
    m = _menu(db, menu_id)
    registry = _registry(request)
    with db.session() as s:
        pages = list(
            s.scalars(
                select(Entry)
                .where(Entry.status == "published")
                .order_by(Entry.type, Entry.title)
                .limit(500)
            )
        )
        terms = list(s.scalars(select(Term).order_by(Term.taxonomy, Term.name).limit(500)))
    nest = request.app.state.nest
    return render(
        request,
        "content/editor/menu.html",
        menu=m,
        items=_items(db, m.id),
        pages=pages,
        terms=terms,
        types=registry.types,
        modules=module_links(request),
        shown=_shown(db, locations(request)),
        translations=nest.plan.unit("translations") is not None,
        here=_here(request),
        error=error,
    )


@menus.post("/menus/{menu_id:int}")
def save_menu(
    request: Request,
    menu_id: int,
    title: str = Form(""),
    action: str = Form("save"),
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    m = _menu(db, menu_id)
    if action == "delete":
        with db.session() as s, s.begin():
            s.delete(s.get(Menu, m.id))
        service.changed()
        return RedirectResponse(_here(request), status_code=303)
    title = title.strip()[:200]
    if title:
        service.ensure_menu(db, m.slug, title)
    return RedirectResponse(f"{_here(request)}/{m.id}", status_code=303)


# --- its items ------------------------------------------------------------------------------


@menus.post("/menus/{menu_id:int}/items")
async def add_item(
    request: Request,
    menu_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    """A link: to a page or an article, a category, a module's pages, or any address."""
    t = translator(request)
    m = _menu(db, menu_id)
    form = await request.form()
    kind = str(form.get("kind", ""))
    title = str(form.get("title", "")).strip()[:200]
    entry_id = term_id = None
    url = ""
    if kind == "entry":
        entry_id = int(form.get("entry_id") or 0) or None
    elif kind == "term":
        term_id = int(form.get("term_id") or 0) or None
    elif kind == "module":
        url = str(form.get("module_url", "")).strip()
        title = title or str(form.get("module_title", "")).strip()
    else:
        url = str(form.get("url", "")).strip()[:1000]
        if url and not re.match(r"^(/|https?://|mailto:|#)", url):
            return menu_page(
                request,
                menu_id,
                user,
                db,
                error=t("An address starts with /, http://, https:// or mailto:."),
            )
    if not (entry_id or term_id or url):
        return menu_page(request, menu_id, user, db, error=t("Choose what the link leads to."))
    if not title and kind in ("custom", "module"):
        return menu_page(request, menu_id, user, db, error=t("A link to an address needs a label."))
    with db.session() as s:
        last = s.scalar(select(func.max(MenuItem.position)).where(MenuItem.menu_id == m.id)) or 0
    item = service.add_menu_item(
        db, m.id, title=title, url=url, entry_id=entry_id, term_id=term_id, position=last + 1,
        new_window=bool(form.get("new_window")),
    )  # fmt: skip
    _mirror(request, db, item.id)
    return RedirectResponse(f"{_here(request)}/{m.id}#item-{item.id}", status_code=303)


def _mirror(request: Request, db: Any, item_id: int) -> None:
    """The item's own label and address, kept as its default language's text."""
    registry = _registry(request)
    with db.session() as s, s.begin():
        item = s.get(MenuItem, item_id)
        if item is not None:
            translated.mirror_menu_item(s, registry, item)


def _item(db: Any, item_id: int) -> MenuItem:
    with db.session() as s:
        item = s.get(MenuItem, item_id)
    if item is None:
        raise HTTPException(404)
    return item


@menus.post("/menus/items/{item_id:int}")
def save_item(
    request: Request,
    item_id: int,
    title: str = Form(""),
    url: str = Form(""),
    new_window: str = Form(""),
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    item = _item(db, item_id)
    with db.session() as s, s.begin():
        row = s.get(MenuItem, item.id)
        row.title = title.strip()[:200]
        if not (row.entry_id or row.term_id):
            row.url = url.strip()[:1000] or row.url
        row.new_window = bool(new_window)
    _mirror(request, db, item.id)
    service.changed()
    return RedirectResponse(f"{_here(request)}/{item.menu_id}#item-{item.id}", status_code=303)


@menus.post("/menus/items/{item_id:int}/move")
def move_item(
    request: Request,
    item_id: int,
    action: str = Form(""),
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    """up, down (among its siblings), in (under the one above it), out (beside its parent)."""
    item = _item(db, item_id)
    with db.session() as s, s.begin():
        row = s.get(MenuItem, item.id)
        siblings = list(
            s.scalars(
                select(MenuItem)
                .where(MenuItem.menu_id == row.menu_id, _under(MenuItem.parent_id, row.parent_id))
                .order_by(MenuItem.position, MenuItem.id)
            )
        )
        for n, sib in enumerate(siblings):  # positions made whole again, in order
            sib.position = n
        i = next(n for n, sib in enumerate(siblings) if sib.id == row.id)
        if action == "up" and i > 0:
            siblings[i - 1].position, row.position = row.position, siblings[i - 1].position
        elif action == "down" and i < len(siblings) - 1:
            siblings[i + 1].position, row.position = row.position, siblings[i + 1].position
        elif action == "in" and i > 0:
            above = siblings[i - 1]
            last = s.scalar(
                select(func.max(MenuItem.position)).where(MenuItem.parent_id == above.id)
            )
            row.parent_id, row.position = above.id, (last or 0) + 1
        elif action == "out" and row.parent_id is not None:
            parent = s.get(MenuItem, row.parent_id)
            row.parent_id, row.position = parent.parent_id, parent.position + 1
            for sib in s.scalars(
                select(MenuItem).where(
                    MenuItem.menu_id == row.menu_id,
                    _under(MenuItem.parent_id, parent.parent_id),
                    MenuItem.position > parent.position,
                    MenuItem.id != row.id,
                )
            ):
                sib.position += 1
    service.changed()
    return RedirectResponse(f"{_here(request)}/{item.menu_id}#item-{item.id}", status_code=303)


@menus.post("/menus/items/{item_id:int}/delete")
def delete_item(
    request: Request,
    item_id: int,
    user: CurrentUser = Depends(editor),
    db: Database = bound(Database),
):
    """The item, and the items under it."""
    item = _item(db, item_id)
    with db.session() as s, s.begin():
        s.delete(s.get(MenuItem, item.id))
    service.changed()
    return RedirectResponse(f"{_here(request)}/{item.menu_id}", status_code=303)
