"""What the comments module does with its records, apart from HTTP."""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select

from nest_comments.models import STATUSES, Comment, utcnow

SUBJECT = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*:[A-Za-z0-9_-]{1,60}$")
MAX_BODY = 5000


class CommentError(ValueError):
    def __init__(self, message: str, **params: object):
        self.message, self.params = message, params
        super().__init__(message.format(**params) if params else message)


@dataclass
class Node:
    comment: Comment
    replies: list[Node] = field(default_factory=list)


def sign(secret: str, subject: str) -> str:
    """A subject a page offers for comments, so a form cannot name another."""
    return hmac.new(secret.encode(), f"comments:{subject}".encode(), hashlib.sha256).hexdigest()[
        :32
    ]


def stamp(secret: str, now: float | None = None) -> str:
    """When a form was shown, signed: a form sent back too quickly is a robot."""
    t = str(int(now if now is not None else time.time()))
    return (
        f"{t}.{hmac.new(secret.encode(), f'stamp:{t}'.encode(), hashlib.sha256).hexdigest()[:16]}"
    )


def stamp_age(secret: str, value: str, now: float | None = None) -> float | None:
    t, _, mac = (value or "").partition(".")
    if not t.isdigit() or not hmac.compare_digest(stamp(secret, int(t)).partition(".")[2], mac):
        return None
    return (now if now is not None else time.time()) - int(t)


def address_hash(secret: str, address: str) -> str:
    """An address kept only as a keyed hash: enough to throttle, not to identify."""
    return hmac.new(secret.encode(), f"ip:{address}".encode(), hashlib.sha256).hexdigest()


def add(
    db: Any,
    subject: str,
    body: str,
    *,
    author_name: str,
    author_email: str = "",
    user_id: int | None = None,
    parent_id: int | None = None,
    status: str = "pending",
    address: str = "",
    max_depth: int = 3,
) -> Comment:
    body = (body or "").strip()
    name = (author_name or "").strip()[:120]
    if not SUBJECT.match(subject):
        raise CommentError("Comments are not open here.")
    if not body:
        raise CommentError("Write something first.")
    if len(body) > MAX_BODY:
        raise CommentError("A comment has at most {n} characters.", n=MAX_BODY)
    if not name:
        raise CommentError("Say who you are.")
    with db.session() as s, s.begin():
        if parent_id is not None:
            parent = s.get(Comment, parent_id)
            if parent is None or parent.subject != subject or parent.status != "approved":
                raise CommentError("That comment can no longer be answered.")
            if depth(s, parent) + 1 >= max_depth:
                parent_id = parent.parent_id  # past the deepest level, answer beside it
        c = Comment(
            subject=subject,
            parent_id=parent_id,
            user_id=user_id,
            author_name=name,
            author_email=author_email.strip()[:254],
            status=status,
            body=body,
            address=address,
            created_at=utcnow(),
        )
        s.add(c)
        s.flush()
        return c


def depth(s: Any, c: Comment) -> int:
    level, seen = 0, {c.id}
    while c.parent_id and c.parent_id not in seen:
        c = s.get(Comment, c.parent_id)
        if c is None:
            break
        seen.add(c.id)
        level += 1
    return level


def thread(db: Any, subject: str) -> tuple[list[Node], int]:
    """The approved comments of a subject, nested, oldest first; and how many there are."""
    with db.session() as s:
        rows = list(
            s.scalars(
                select(Comment)
                .where(Comment.subject == subject, Comment.status == "approved")
                .order_by(Comment.created_at, Comment.id)
            )
        )
    nodes = {c.id: Node(c) for c in rows}
    roots: list[Node] = []
    for c in rows:
        parent = nodes.get(c.parent_id) if c.parent_id else None
        (parent.replies if parent else roots).append(nodes[c.id])
    return roots, len(rows)


def counts(db: Any, subjects: list[str]) -> dict[str, int]:
    with db.session() as s:
        return dict(
            s.execute(
                select(Comment.subject, func.count())
                .where(Comment.subject.in_(subjects), Comment.status == "approved")
                .group_by(Comment.subject)
            ).all()
        )


def queue(db: Any, status: str = "pending", limit: int = 100) -> list[Comment]:
    with db.session() as s:
        return list(
            s.scalars(
                select(Comment)
                .where(Comment.status == status)
                .order_by(Comment.created_at.desc())
                .limit(limit)
            )
        )


def set_status(db: Any, comment_id: int, status: str) -> Comment | None:
    if status not in STATUSES:
        raise CommentError("Unknown status '{status}'.", status=status)
    with db.session() as s, s.begin():
        c = s.get(Comment, comment_id)
        if c is not None:
            c.status = status
        return c
