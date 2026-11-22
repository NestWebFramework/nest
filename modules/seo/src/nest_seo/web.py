"""The seo module over HTTP: /sitemap.xml with the photos, /robots.txt, and the admin overview.

Every module that has public pages answers "seo.urls" with them: a list of dicts with
``path``, and optionally ``title``, ``subject``, ``lastmod``, ``images`` ([{key or url,
title, caption}]), ``edit`` (its editor's address) and ``kind``. A page its editors
hid from search engines (noindex) is left out of the sitemap.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape as xml

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from nest_auth import CurrentUser, require_role
from starlette.concurrency import run_in_threadpool

from nest import render
from nest_seo import service
from nest_seo.head import absolute, picture
from nest_seo.suggest import propose

root = APIRouter()
admin = APIRouter()
editor = require_role("editor")


def pages(request: Request) -> list[dict[str, Any]]:
    """Every public page the application's modules offer, once each."""
    seen, out = set(), []
    for answer in request.app.state.nest.gather("seo.urls"):
        for item in answer or []:
            path = item.get("path")
            if path and path not in seen:
                seen.add(path)
                out.append(item)
    return out


@root.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request) -> Response:
    db = request.app.state.nest.bindings.get("nest.db")
    items = pages(request)
    metas = service.many(db, [i.get("subject", "") for i in items])
    rows = []
    for item in items:
        meta = metas.get(item.get("subject", ""))
        if meta is not None and meta.noindex:
            continue
        own = meta.canonical if meta and meta.canonical and not item.get("language") else ""
        loc = absolute(request, own or item["path"])  # a translated page is its own
        row = f"<url><loc>{xml(loc)}</loc>"
        when = item.get("lastmod")
        if isinstance(when, datetime):
            row += f"<lastmod>{when.date().isoformat()}</lastmod>"
        for image in (item.get("images") or [])[:1000]:
            src = picture(request, image.get("key", ""), None) or image.get("url", "")
            if not src:
                continue
            row += f"<image:image><image:loc>{xml(src)}</image:loc>"
            if image.get("title"):
                row += f"<image:title>{xml(image['title'])}</image:title>"
            if image.get("caption"):
                row += f"<image:caption>{xml(image['caption'])}</image:caption>"
            row += "</image:image>"
        rows.append(row + "</url>")
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
        + "".join(rows)
        + "</urlset>"
    )
    return Response(
        body, media_type="application/xml", headers={"Cache-Control": "public, max-age=3600"}
    )


@root.get("/robots.txt", include_in_schema=False)
def robots(request: Request) -> Response:
    nest = request.app.state.nest
    settings = nest.module_state["seo"]["settings"]
    closed = [nest.admin_root] if nest.admin_root else []
    for unit in nest.plan.units:
        if unit.name == "auth" and unit.instance and unit.instance.route:
            closed.append(unit.instance.route)
    closed += [
        p.strip()
        for p in str(settings.get("robots_closed") or "").split(",")
        if p.strip().startswith("/")
    ]
    text = nest.templates.get_template("seo/robots.txt").render(
        production=nest.production,
        closed=sorted({c.rstrip("/") + "/" for c in closed} | {"/_nest/"}),
        sitemap=absolute(request, "/sitemap.xml"),
    )
    return Response(
        text, media_type="text/plain", headers={"Cache-Control": "public, max-age=3600"}
    )


@admin.post("/suggest")
async def suggest(request: Request, user: CurrentUser = Depends(editor)) -> JSONResponse:
    """A proposal for a page's search fields, from the text an editor is writing."""
    form = await request.form()
    texts = [str(v) for k, v in form.multi_items() if k == "text"][:200]
    context = [str(v)[:100] for k, v in form.multi_items() if k == "context"][:20]
    subject = str(form.get("subject", ""))[:200]
    if subject:  # what the page holds besides its form: a category's entries, say
        found = request.app.state.nest.lookup("seo.text", subject) or {}
        words = found.get("words") or {}
        if words.get("description"):  # the module writes the page's words itself
            return JSONResponse(
                {f: str(words.get(f) or "") for f in ("title", "description", "keywords")}
            )
        texts = [*texts, *found.get("lead", [])]
        extra = found.get("text", [])
        context += found.get("context", [])
    else:
        extra = []
    p = propose(
        str(form.get("title", ""))[:300],
        *[t[:50000] for t in texts],
        context=context,
        site=request.app.state.nest.title,
        more=extra,
        plain_title=subject.startswith("content.term:"),
    )
    return JSONResponse({"title": p.title, "description": p.description, "keywords": p.keywords})


def _rows(request: Request) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    db = request.app.state.nest.bindings.get("nest.db")
    items = pages(request)
    metas = service.many(db, [i.get("subject", "") for i in items])
    rows = []
    for item in items:
        meta = metas.get(item.get("subject", ""))
        rows.append(
            {
                "item": item,
                "meta": meta,
                "group": item.get("group") or item.get("kind") or "Other",
                "described": bool((meta and meta.description) or item.get("description")),
                "pictures": len(item.get("images") or []),
            }
        )
    return rows, metas


@admin.get("/")
def overview(
    request: Request, group: str = "", missing: int = 0, user: CurrentUser = Depends(editor)
):
    """How each page shows in search results, a tab per kind of page (articles, pages,
    galleries...): what is said of it, what is missing."""
    rows, metas = _rows(request)
    groups: dict[str, dict[str, int]] = {}
    for r in rows:
        g = groups.setdefault(r["group"], {"pages": 0, "missing": 0})
        g["pages"] += 1
        g["missing"] += 0 if r["described"] else 1
    # the home page first, then the kinds of content, their categories, galleries, maps
    rank = {"Home": 0, "Categories": 50, "Galleries": 60, "Maps": 70}
    groups = dict(sorted(groups.items(), key=lambda kv: rank.get(kv[0], 10)))
    current = group if group in groups else (next(iter(groups)) if groups else "")
    shown = [r for r in rows if r["group"] == current and (not missing or not r["described"])]
    return render(
        request,
        "seo/overview.html",
        rows=shown,
        groups=groups,
        current=current,
        missing=missing,
        total=len(rows),
        undescribed=sum(g["missing"] for g in groups.values()),
        hidden=sum(1 for m in metas.values() if m.noindex),
        photos=sum(r["pictures"] for r in rows),
        can_propose=sum(
            1
            for r in rows
            if r["group"] == current
            and not r["described"]
            and r["item"].get("subject")
            and r["item"].get("text")
        ),
    )


@admin.post("/propose")
async def propose_missing(request: Request, user: CurrentUser = Depends(editor)):
    """Descriptions (and keywords) proposed from their text for the pages of a tab that
    have none: written as editors would, to read and correct page by page."""
    from fastapi.responses import RedirectResponse

    from nest import toast, translator

    form = await request.form()
    group = str(form.get("group", ""))
    db = request.app.state.nest.bindings.get("nest.db")
    rows, metas = _rows(request)
    done = 0
    for r in rows:
        item = r["item"]
        subject = item.get("subject")
        if r["group"] != group or r["described"] or not subject or not item.get("text"):
            continue
        p = propose(item.get("title") or "", *item["text"], site=request.app.state.nest.title)
        if not p.description:
            continue
        meta = metas.get(subject)
        values = service.Values(
            title=meta.title if meta else "",
            description=p.description,
            keywords=(meta.keywords if meta and meta.keywords else p.keywords),
            image=meta.image if meta else "",
            canonical=meta.canonical if meta else "",
            noindex=bool(meta and meta.noindex),
        )
        service.save(db, subject, values)
        done += 1
    t = translator(request)
    toast(
        request,
        t.ngettext(
            "{n} description proposed: read it and correct what is wrong.",
            "{n} descriptions proposed: read them and correct what is wrong.",
            done,
        ),
    )
    from urllib.parse import quote as q

    return RedirectResponse(
        f"{request.app.state.nest.admin_root}/seo/?group={q(group)}", status_code=303
    )


# --- batches: the search fields of many pages at once ------------------------------------


def _groups(rows: list[dict[str, Any]]) -> list[str]:
    rank = {"Home": 0, "Categories": 50, "Galleries": 60, "Maps": 70}
    return sorted({r["group"] for r in rows}, key=lambda g: (rank.get(g, 10), g))


@admin.get("/batch")
def batch_form(request: Request, group: str = "", user: CurrentUser = Depends(editor)):
    """Step one: which pages, which fields, how."""
    from nest_seo import batch

    rows, _metas = _rows(request)
    groups = _groups(rows)
    return render(
        request,
        "seo/batch.html",
        step="choose",
        groups=groups,
        counts={g: sum(1 for r in rows if r["group"] == g) for g in groups},
        chosen=[group] if group in groups else groups,
        fields=list(batch.FIELDS),
        only_empty=True,
        can_undo=batch.last(request.app.state.nest) is not None,
    )


@admin.post("/batch/preview")
async def batch_preview(request: Request, user: CurrentUser = Depends(editor)):
    """Step two: page by page, what each field holds and what would be written."""
    from nest_seo import batch

    form = await request.form()
    chosen = [str(g) for g in form.getlist("group")]
    fields = [f for f in form.getlist("field") if f in batch.FIELDS]
    only_empty = str(form.get("mode", "empty")) != "all"
    rows, metas = _rows(request)
    items = [r["item"] for r in rows if r["group"] in chosen]
    planned = batch.plan(request.app.state.nest, items, metas, fields, only_empty)
    return render(
        request,
        "seo/batch.html",
        step="preview",
        rows=planned,
        fields=fields,
        only_empty=only_empty,
        changing=sum(1 for r in planned if r["changes"]),
        chosen=chosen,
    )


@admin.post("/batch/apply")
async def batch_apply(request: Request, user: CurrentUser = Depends(editor)):
    """Step three: the checked pages saved; what they held kept, to undo."""
    from fastapi.responses import RedirectResponse

    from nest import toast, translator
    from nest_seo import batch

    form = await request.form()
    db = request.app.state.nest.bindings.get("nest.db")
    # the preview's choice again; each page's values proposed anew (as the preview showed
    # them), so the form stays small however many pages the batch has
    groups = [str(g) for g in form.getlist("group")]
    fields = [f for f in form.getlist("field") if f in batch.FIELDS]
    only_empty = str(form.get("mode", "empty")) != "all"
    skip = {str(x) for x in form.getlist("skip")}
    rows, metas = _rows(request)
    items = [r["item"] for r in rows if r["group"] in groups]
    planned = await run_in_threadpool(
        batch.plan, request.app.state.nest, items, metas, fields, only_empty
    )
    chosen: dict[str, dict[str, str]] = {
        r["subject"]: {f: c["new"] for f, c in r["changes"].items()}
        for r in planned
        if r["changes"] and r["subject"] not in skip
    }
    t = translator(request)
    try:
        done = batch.apply(request.app.state.nest, db, chosen) if chosen else 0
    except service.SeoError as e:
        toast(request, t(e.message, **e.params), "error")
        done = 0
    toast(
        request,
        t.ngettext(
            "{n} page updated. You can undo it from the batch page.",
            "{n} pages updated. You can undo it from the batch page.",
            done,
        ),
    )
    return RedirectResponse(f"{request.app.state.nest.admin_root}/seo/", status_code=303)


@admin.post("/batch/undo")
def batch_undo(request: Request, user: CurrentUser = Depends(editor)):
    from fastapi.responses import RedirectResponse

    from nest import toast, translator
    from nest_seo import batch

    db = request.app.state.nest.bindings.get("nest.db")
    done = batch.undo(request.app.state.nest, db)
    t = translator(request)
    toast(
        request,
        t.ngettext("{n} page is back as it was.", "{n} pages are back as they were.", done)
        if done
        else t("There is no batch to undo."),
    )
    return RedirectResponse(f"{request.app.state.nest.admin_root}/seo/batch", status_code=303)
