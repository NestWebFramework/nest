"""The documentation's pages: the front page, each page with the menu and its contents,
search, the pictures, and the site's home (landing.md) when the application wants it."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from nest_search import Document, Search

from nest import bound, render
from nest.host import module_state
from nest_docs.tree import Tree

router = APIRouter()
home_router = APIRouter()
KIND = "docs.page"


def _tree(request: Request) -> Tree:
    return module_state(request, "docs")["tree"]


def _index(request: Request, search: Any) -> None:
    """The pages into the search index, once a process (again when they are reloaded)."""
    state = module_state(request, "docs")
    if state.get("indexed"):
        return
    tree = _tree(request)
    docs = [
        Document(
            kind=KIND,
            id=e.key,
            title=page.title or e.title,
            body=page.text,
            url=tree.url(e.key),
            scope=e.section or "",
        )
        for e, page in tree.all_pages()
    ]
    search.clear(KIND)
    if docs:
        search.index(docs)
    state["indexed"] = True


def _page(request: Request, key: str, *, status: int = 200) -> Response:
    tree = _tree(request)
    page = tree.page(key)
    if page is None:
        return render(request, "docs/missing.html", status_code=404, tree=tree, current=key)
    before, after = tree.neighbours(key)
    edit = module_state(request, "docs")["edit_url"]
    entry = tree.entries[key]
    return render(
        request,
        "docs/page.html",
        status_code=status,
        tree=tree,
        current=key,
        page=page,
        section=entry.section,
        toc=[h for h in page.headings if h.level in (2, 3)],
        before=before,
        after=after,
        edit=(edit.format(path=f"{key}.md") if edit and entry.file is not None else ""),
    )


@router.get("/")
def front(request: Request):
    return _page(request, "index")


@router.get("/search")
def search_page(request: Request, q: str = "", search: Search = bound(Search)):
    _index(request, search)
    q = q.strip()[:200]
    hits = search.query(q, kind=KIND, limit=30) if q else []
    return render(
        request,
        "docs/search.html",
        fragment="results",
        tree=_tree(request),
        current="",
        q=q,
        hits=hits,
    )


@router.get("/_files/{path:path}")
def media(request: Request, path: str):
    found = _tree(request).file(path)
    if found is None:
        raise HTTPException(404)
    return FileResponse(found, headers={"cache-control": "public, max-age=86400"})


@router.get("/{key:path}")
def page(request: Request, key: str):
    key = key.strip("/").removesuffix(".md") or "index"
    return _page(request, key)


@home_router.get("/")
def landing(request: Request):
    tree = _tree(request)
    page = tree.page("landing")
    if page is None:
        return _page(request, "index")
    return render(request, "docs/landing.html", tree=tree, page=page, meta=page.meta)
