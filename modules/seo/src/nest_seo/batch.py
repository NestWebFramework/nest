"""Search fields for many pages at once: proposed from each page's text, seen, then applied.

A batch is chosen (the pages of a tab or all of them; which fields; only the empty ones
or all), previewed page by page (what each field holds, what would be written), and the
checked pages are saved. What they held before is kept in the workspace
(data/seo-batches/), so the last batch can be undone whole.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nest_seo import service
from nest_seo.suggest import propose

FIELDS = ("title", "description", "keywords")


def proposal(nest: Any, item: dict[str, Any]) -> dict[str, str]:
    """The proposal for one page of the sitemap, as the editor's button makes it."""
    texts = list(item.get("text") or [])
    context = list(item.get("context") or [])
    more: list[str] = []
    subject = item.get("subject") or ""
    if subject:
        found = nest.lookup("seo.text", subject) or {}
        words = found.get("words") or {}
        if words.get("description"):  # the module writes the page's words itself: as they are
            return {f: str(words.get(f) or "") for f in FIELDS}
        texts += found.get("lead", [])
        more = found.get("text", [])
        context += found.get("context", [])
    p = propose(
        item.get("title") or "",
        *texts,
        context=context,
        site=nest.title,
        more=more,
        plain_title=subject.startswith("content.term:"),
    )
    return {"title": p.title, "description": p.description, "keywords": p.keywords}


def plan(
    nest: Any,
    items: list[dict[str, Any]],
    metas: dict[str, Any],
    fields: list[str],
    only_empty: bool,
) -> list[dict[str, Any]]:
    """Each page with, for each chosen field, what it holds and what would be written."""
    rows = []
    for item in items:
        subject = item.get("subject")
        if not subject:
            continue
        meta = metas.get(subject)
        offer = proposal(nest, item)
        changes = {}
        for f in fields:
            now = getattr(meta, f) if meta else ""
            new = offer.get(f, "")
            if not new or new == now or (only_empty and now):
                continue
            changes[f] = {"now": now, "new": new}
        rows.append({"item": item, "subject": subject, "changes": changes})
    return rows


def _folder(nest: Any) -> Path:
    folder = nest.workspace / "data" / "seo-batches"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def apply(nest: Any, db: Any, chosen: dict[str, dict[str, str]]) -> int:
    """Save ``{subject: {field: value}}``, keeping what each held before (to undo)."""
    metas = service.many(db, list(chosen))
    before = {}
    for subject, values in chosen.items():
        meta = metas.get(subject)
        old = {n: getattr(meta, n) for n in service.FIELDS} if meta else None
        before[subject] = old
        merged = {**(old or {n: "" for n in service.FIELDS}), **values}
        merged["noindex"] = bool(merged.get("noindex"))
        service.save(db, subject, service.clean(merged))
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    (_folder(nest) / f"{stamp}.json").write_text(
        json.dumps(before, ensure_ascii=False), encoding="utf-8"
    )
    return len(chosen)


def last(nest: Any) -> Path | None:
    found = sorted(_folder(nest).glob("*.json"))
    return found[-1] if found else None


def undo(nest: Any, db: Any) -> int:
    """The last batch taken back: each page as it was before it."""
    path = last(nest)
    if path is None:
        return 0
    before = json.loads(path.read_text(encoding="utf-8"))
    for subject, old in before.items():
        if old is None:
            service.forget(db, subject)
        else:
            old["noindex"] = bool(old.get("noindex"))
            service.save(db, subject, service.clean(old))
    path.unlink()
    return len(before)
