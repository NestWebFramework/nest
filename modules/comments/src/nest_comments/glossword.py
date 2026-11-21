"""A Glossword site's comments (GentleSource Comment Script: tables cmt_comment and
cmt_identifier), attached to wherever their terms went.

The comments module does not know the glossary: it asks the application's
"glossary.legacy_subject" lookup which subject a comment's old address
(/index.php/term/Graiul+moldovenesc,untariță) became, and skips comments whose term did
not come across. Approved stays approved (status 0); what its spam filters held back
(100) is spam. Run again, it updates what it brought in before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nest_db import Dump
from sqlalchemy import select

from nest.text import html_to_text
from nest_comments.models import Comment

STATUS = {"0": "approved", "100": "spam"}


@dataclass
class Report:
    comments: int = 0
    skipped: int = 0
    orphans: list[str] = field(default_factory=list)


def _none(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text == "None" else text


def import_dump(db: Any, lookup: Any, dump_path: Path, *, prefix: str = "cmt_") -> Report:
    report = Report()
    dump = Dump.read(dump_path)
    ours: dict[int, int] = {}
    with db.session() as s:
        for legacy, cid in s.execute(
            select(Comment.legacy_id, Comment.id).where(Comment.legacy_source == "glossword")
        ):
            ours[legacy] = cid
    for r in sorted(dump.rows(f"{prefix}comment"), key=lambda r: int(r["comment_id"])):
        status = STATUS.get(str(r["comment_status"]))
        if status is None:
            report.skipped += 1
            continue
        address = _none(r["comment_identifier"])
        target = lookup("glossary.legacy_subject", address)
        if target is None:
            report.orphans.append(address)
            continue
        legacy_id = int(r["comment_id"])
        stamp = str(r["comment_timestamp"] or "")
        created = (
            datetime.fromtimestamp(int(stamp), UTC).replace(tzinfo=None)
            if stamp.isdigit()
            else datetime.now(UTC).replace(tzinfo=None)
        )
        with db.session() as s, s.begin():
            c = s.get(Comment, ours[legacy_id]) if legacy_id in ours else None
            if c is None:
                c = Comment(legacy_source="glossword", legacy_id=legacy_id)
                s.add(c)
            c.subject, c.parent_id, c.status = target, None, status
            c.author_name = (_none(r["comment_author_name"]) or "Anonim")[:120]
            c.author_email = _none(r["comment_author_email"])[:254]
            c.body = html_to_text(_none(r["comment_text"])) or "…"
            c.created_at = created
            c.user_id = None
            s.flush()
            ours[legacy_id] = c.id
        report.comments += 1
    return report
