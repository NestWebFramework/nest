"""WordPress comments, attached to wherever their posts went.

The comments module does not know the content module: it asks the
application's "wordpress.post" lookup which subject an old post became, and
skips comments whose post did not come across. Approved comments stay
approved, waiting ones wait, spam stays spam; trash is left behind. Replies
keep their parents. Bodies become plain text.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from nest_db import Dump
from sqlalchemy import select

from nest.text import html_to_text
from nest_comments.models import Comment

STATUS = {"1": "approved", "0": "pending", "spam": "spam"}


@dataclass
class Report:
    comments: int = 0
    skipped: int = 0
    orphans: list[int] = field(default_factory=list)


def import_dump(db: Any, lookup: Any, dump_path: Path, *, prefix: str = "wp_") -> Report:
    report = Report()
    dump = Dump.read(dump_path)
    rows = sorted(dump.rows(f"{prefix}comments"), key=lambda r: int(r["comment_ID"]))
    ours: dict[int, int] = {}
    with db.session() as s:
        for legacy, cid in s.execute(
            select(Comment.legacy_id, Comment.id).where(Comment.legacy_source == "wordpress")
        ):
            ours[legacy] = cid
    for r in rows:
        status = STATUS.get(str(r["comment_approved"]))
        kind = str(r.get("comment_type") or "")
        if status is None or kind in ("pingback", "trackback"):
            report.skipped += 1
            continue
        target = lookup("wordpress.post", int(r["comment_post_ID"]))
        if target is None:
            report.orphans.append(int(r["comment_ID"]))
            continue
        legacy_id = int(r["comment_ID"])
        try:
            created = datetime.fromisoformat(str(r["comment_date_gmt"] or r["comment_date"]))
        except ValueError:
            created = datetime.fromisoformat(str(r["comment_date"]))
        parent = ours.get(int(r["comment_parent"] or 0))
        with db.session() as s, s.begin():
            c = s.get(Comment, ours[legacy_id]) if legacy_id in ours else None
            if c is None:
                c = Comment(legacy_source="wordpress", legacy_id=legacy_id)
                s.add(c)
            c.subject, c.parent_id, c.status = target["subject"], parent, status
            c.author_name = (html.unescape(r["comment_author"] or "") or "Anonim")[:120]
            c.author_email = (r["comment_author_email"] or "")[:254]
            c.body = html_to_text(r["comment_content"] or "") or "…"
            c.created_at = created
            c.user_id = None
            s.flush()
            ours[legacy_id] = c.id
        report.comments += 1
    return report
