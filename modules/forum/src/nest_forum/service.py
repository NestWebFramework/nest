"""What the forum does with its records, apart from HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select

from nest.text import slugify
from nest_forum.models import Board, Post, Topic, utcnow

MAX_BODY = 20000


class ForumError(ValueError):
    def __init__(self, message: str, **params: object):
        self.message, self.params = message, params
        super().__init__(message.format(**params) if params else message)


@dataclass
class BoardRow:
    board: Board
    topics: int
    posts: int
    last: Topic | None


def ensure_board(
    db: Any,
    title: str,
    *,
    slug: str = "",
    description: str = "",
    position: int | None = None,
    scope: str | None = None,
    parent: Board | None = None,
) -> Board:
    """The board of this slug (or, with a scope and no parent, the scope's own board), made
    if missing. A board made in another (``parent``) takes its scope."""
    slug = slugify(slug or title)
    if parent is not None:
        scope = parent.scope
    with db.session() as s, s.begin():
        if scope and parent is None:
            b = s.scalar(select(Board).where(Board.scope == scope, Board.parent_id.is_(None)))
        else:
            b = s.scalar(select(Board).where(Board.slug == slug))
        if b is None:
            taken = s.scalar(select(func.count()).select_from(Board).where(Board.slug == slug))
            if taken:  # a scoped board's slug never takes another's
                slug = f"{slug}-{s.scalar(select(func.max(Board.id))) or 0}"
            count = s.scalar(select(func.count()).select_from(Board)) or 0
            b = Board(
                slug=slug,
                title=title,
                position=count if position is None else position,
                scope=scope or None,
                parent_id=parent.id if parent is not None else None,
            )
            s.add(b)
        b.title, b.description = title, description or b.description
        s.flush()
        return b


def boards(db: Any, *, scoped: bool = False, parent_id: int | None = None) -> list[BoardRow]:
    """The forum's own public boards (the index); the boards in a board (``parent_id``);
    with scoped, every board (the admin panel)."""
    with db.session() as s:
        q = select(Board).order_by(Board.position, Board.title)
        if parent_id is not None:
            q = q.where(Board.parent_id == parent_id)
        elif not scoped:
            q = q.where(Board.scope.is_(None), Board.parent_id.is_(None))
        rows = list(s.scalars(q))
        stats = dict(
            (b, (t, p))
            for b, t, p in s.execute(
                select(Topic.board_id, func.count(), func.coalesce(func.sum(Topic.posts), 0))
                .where(Topic.hidden.is_(False))
                .group_by(Topic.board_id)
            ).all()
        )
        out = []
        for b in rows:
            last = s.scalar(
                select(Topic)
                .where(Topic.board_id == b.id, Topic.hidden.is_(False))
                .order_by(Topic.last_post_at.desc())
                .limit(1)
            )
            topics, posts = stats.get(b.id, (0, 0))
            out.append(BoardRow(b, topics, int(posts), last))
        return out


def trail(db: Any, b: Board) -> list[Board]:
    """The boards a board is in, the outermost first (for the way back up)."""
    out: list[Board] = []
    with db.session() as s:
        at = b.parent_id
        while at is not None and len(out) < 32:  # never a loop
            parent = s.get(Board, at)
            if parent is None:
                break
            out.insert(0, parent)
            at = parent.parent_id
        s.expunge_all()
    return out


def board(db: Any, slug: str) -> Board | None:
    with db.session() as s:
        return s.scalar(select(Board).where(Board.slug == slug))


def topics(
    db: Any,
    board_id: int,
    *,
    page: int,
    per_page: int,
    include_hidden: bool = False,
    archived: bool = False,
) -> tuple[list[Topic], int]:
    with db.session() as s:
        q = select(Topic).where(Topic.board_id == board_id)
        q = q.where(Topic.archived.is_(archived))  # the open topics, or those put away
        if not include_hidden:
            q = q.where(Topic.hidden.is_(False))
        total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = s.scalars(
            q.order_by(Topic.pinned.desc(), Topic.last_post_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return list(rows), total


def topic(db: Any, topic_id: int) -> Topic | None:
    with db.session() as s:
        return s.get(Topic, topic_id)


def posts(
    db: Any, topic_id: int, *, page: int, per_page: int, include_hidden: bool = False
) -> tuple[list[Post], int]:
    with db.session() as s:
        q = select(Post).where(Post.topic_id == topic_id)
        if not include_hidden:
            q = q.where(Post.hidden.is_(False))
        total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = s.scalars(
            q.order_by(Post.created_at, Post.id).offset((page - 1) * per_page).limit(per_page)
        )
        return list(rows), total


def post(db: Any, post_id: int) -> Post | None:
    with db.session() as s:
        return s.get(Post, post_id)


def _check_body(body: str) -> str:
    body = (body or "").strip()
    if not body:
        raise ForumError("Write something first.")
    if len(body) > MAX_BODY:
        raise ForumError("A post has at most {n} characters.", n=MAX_BODY)
    return body


def recent_posts(db: Any, author_id: int, minutes: int = 1) -> int:
    with db.session() as s:
        return (
            s.scalar(
                select(func.count())
                .select_from(Post)
                .where(
                    Post.author_id == author_id,
                    Post.created_at > utcnow() - timedelta(minutes=minutes),
                )
            )
            or 0
        )


def start_topic(db: Any, b: Board, author_id: int, title: str, body: str) -> tuple[Topic, Post]:
    title = (title or "").strip()
    if not title:
        raise ForumError("A topic needs a title.")
    if len(title) > 200:
        raise ForumError("A title has at most {n} characters.", n=200)
    if b.locked or archived_in(db, b):
        raise ForumError("This board is closed.")
    body = _check_body(body)
    now = utcnow()
    with db.session() as s, s.begin():
        t = Topic(
            board_id=b.id,
            slug=slugify(title, max_length=180),
            title=title,
            author_id=author_id,
            created_at=now,
            last_post_at=now,
            last_author_id=author_id,
            posts=1,
        )
        s.add(t)
        s.flush()
        p = Post(topic_id=t.id, author_id=author_id, body=body, created_at=now)
        s.add(p)
        s.flush()
        return t, p


def reply(db: Any, topic_id: int, author_id: int, body: str) -> Post:
    body = _check_body(body)
    now = utcnow()
    with db.session() as s, s.begin():
        t = s.get(Topic, topic_id)
        if t is None or t.hidden:
            raise ForumError("This topic no longer exists.")
        if t.locked or t.archived:
            raise ForumError("This topic is closed.")
        p = Post(topic_id=t.id, author_id=author_id, body=body, created_at=now)
        s.add(p)
        t.posts += 1
        t.last_post_at, t.last_author_id = now, author_id
        s.flush()
        return p


def edit(db: Any, post_id: int, body: str) -> Post:
    body = _check_body(body)
    with db.session() as s, s.begin():
        p = s.get(Post, post_id)
        if p is None:
            raise ForumError("This post no longer exists.")
        t = s.get(Topic, p.topic_id)
        if t is not None and t.archived:
            raise ForumError("This topic is closed.")
        p.body, p.edited_at = body, utcnow()
        return p


def may_edit(p: Post, user: Any, minutes: int) -> bool:
    if user is None:
        return False
    if user.has("moderator"):
        return True
    return p.author_id == user.id and utcnow() - p.created_at < timedelta(minutes=minutes)


def moderate_topic(db: Any, topic_id: int, action: str) -> Topic | None:
    flags = {
        "pin": ("pinned", True),
        "unpin": ("pinned", False),
        "lock": ("locked", True),
        "unlock": ("locked", False),
        "hide": ("hidden", True),
        "show": ("hidden", False),
        "archive": ("archived", True),
        "unarchive": ("archived", False),
    }
    if action not in flags:
        raise ForumError("Unknown action.")
    with db.session() as s, s.begin():
        t = s.get(Topic, topic_id)
        if t is not None:
            setattr(t, *flags[action])
        return t


def hide_post(db: Any, post_id: int, hidden: bool = True) -> Post | None:
    with db.session() as s, s.begin():
        p = s.get(Post, post_id)
        if p is not None and p.hidden != hidden:
            p.hidden = hidden
            t = s.get(Topic, p.topic_id)
            t.posts += -1 if hidden else 1
        return p


def count_view(db: Any, topic_id: int) -> None:
    with db.session() as s, s.begin():
        t = s.get(Topic, topic_id)
        if t is not None:
            t.views += 1


def board_by_id(db: Any, board_id: int) -> Board | None:
    with db.session() as s:
        return s.get(Board, board_id)


def archived_in(db: Any, b: Board) -> bool:
    """Whether a board is put away, itself or with a board it is in (then it is too)."""
    return bool(b.archived) or any(p.archived for p in trail(db, b))


def _subtree(s: Any, board_id: int) -> list[int]:
    """A board and every board in it, to any depth."""
    out, todo = [board_id], [board_id]
    while todo and len(out) < 100_000:
        todo = list(s.scalars(select(Board.id).where(Board.parent_id.in_(todo))))
        todo = [i for i in todo if i not in out]  # never a loop
        out += todo
    return out


def reach(db: Any, board_id: int) -> dict[str, int]:
    """What deleting a board removes: its boards (itself too), their topics and posts."""
    with db.session() as s:
        ids = _subtree(s, board_id)
        topics = select(Topic.id).where(Topic.board_id.in_(ids))
        return {
            "boards": len(ids),
            "topics": s.scalar(select(func.count()).select_from(topics.subquery())) or 0,
            "posts": s.scalar(
                select(func.count()).select_from(Post).where(Post.topic_id.in_(topics))
            )
            or 0,
        }


def archive_board(db: Any, board_id: int, archived: bool = True) -> Board | None:
    """Put a board away (or back): what is in it goes with it, as it is in it."""
    with db.session() as s, s.begin():
        b = s.get(Board, board_id)
        if b is not None:
            b.archived = archived
        return b


def update_board(
    db: Any, board_id: int, *, title: str, description: str, position: int | None = None
) -> Board | None:
    with db.session() as s, s.begin():
        b = s.get(Board, board_id)
        if b is not None:
            b.title, b.description = title, description
            if position is not None:
                b.position = position
        return b


def delete_board(db: Any, board_id: int) -> dict[str, int]:
    """Delete a board with every board in it, their topics and their posts (not left to
    the database's cascades, which SQLite keeps only when told to)."""
    counts = reach(db, board_id)
    with db.session() as s, s.begin():
        ids = _subtree(s, board_id)
        topics = select(Topic.id).where(Topic.board_id.in_(ids))
        s.execute(delete(Post).where(Post.topic_id.in_(topics)))
        s.execute(delete(Topic).where(Topic.board_id.in_(ids)))
        for i in reversed(ids):  # the innermost first
            s.execute(delete(Board).where(Board.id == i))
    return counts


def delete_topic(db: Any, topic_id: int) -> Topic | None:
    """Delete a topic and its posts; the topic as it was (for where to go next)."""
    with db.session() as s, s.begin():
        t = s.get(Topic, topic_id)
        if t is not None:
            s.execute(delete(Post).where(Post.topic_id == topic_id))
            s.delete(t)
            s.flush()
            s.expunge(t)
        return t
