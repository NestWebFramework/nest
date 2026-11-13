"""What the messages module does with its records, apart from HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from nest_messages.models import Conversation, Message, Participant, utcnow

MAX_BODY = 10000


class MessageError(ValueError):
    def __init__(self, message: str, **params: object):
        self.message, self.params = message, params
        super().__init__(message.format(**params) if params else message)


@dataclass
class InboxRow:
    conversation: Conversation
    last: Message | None
    unread: bool
    others: list[int]


def _body(body: str) -> str:
    body = (body or "").strip()
    if not body:
        raise MessageError("Write something first.")
    if len(body) > MAX_BODY:
        raise MessageError("A message has at most {n} characters.", n=MAX_BODY)
    return body


def start(
    db: Any, sender_id: int, recipients: list[int], subject: str, body: str
) -> tuple[Conversation, Message]:
    others = sorted(set(recipients) - {sender_id})
    if not others:
        raise MessageError("Write to someone other than yourself.")
    body = _body(body)
    now = utcnow()
    with db.session() as s, s.begin():
        c = Conversation(subject=(subject or "").strip()[:200], created_at=now, last_message_at=now)
        s.add(c)
        s.flush()
        s.add(Participant(conversation_id=c.id, user_id=sender_id, last_read_at=now))
        for uid in others:
            s.add(Participant(conversation_id=c.id, user_id=uid, last_read_at=None))
        m = Message(conversation_id=c.id, sender_id=sender_id, body=body, created_at=now)
        s.add(m)
        s.flush()
        return c, m


def reply(db: Any, conversation_id: int, sender_id: int, body: str) -> Message:
    body = _body(body)
    now = utcnow()
    with db.session() as s, s.begin():
        me = s.get(Participant, (conversation_id, sender_id))
        if me is None:
            raise MessageError("This conversation does not exist.")
        m = Message(conversation_id=conversation_id, sender_id=sender_id, body=body, created_at=now)
        s.add(m)
        s.get(Conversation, conversation_id).last_message_at = now
        s.execute(
            update(Participant)
            .where(Participant.conversation_id == conversation_id)
            .values(archived=False)
        )
        me.last_read_at = now
        s.flush()
        return m


def participants(db: Any, conversation_id: int) -> list[int]:
    with db.session() as s:
        return list(
            s.scalars(
                select(Participant.user_id).where(Participant.conversation_id == conversation_id)
            )
        )


def conversation(db: Any, conversation_id: int, user_id: int) -> Conversation | None:
    """The conversation, only for someone who takes part in it."""
    with db.session() as s:
        if s.get(Participant, (conversation_id, user_id)) is None:
            return None
        return s.get(Conversation, conversation_id)


def messages(db: Any, conversation_id: int, limit: int = 200) -> list[Message]:
    with db.session() as s:
        rows = list(
            s.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit)
            )
        )
        return rows[::-1]


def mark_read(db: Any, conversation_id: int, user_id: int) -> None:
    with db.session() as s, s.begin():
        p = s.get(Participant, (conversation_id, user_id))
        if p is not None:
            p.last_read_at = utcnow()


def archive(db: Any, conversation_id: int, user_id: int) -> None:
    with db.session() as s, s.begin():
        p = s.get(Participant, (conversation_id, user_id))
        if p is not None:
            p.archived = True


def inbox(db: Any, user_id: int, *, archived: bool = False) -> list[InboxRow]:
    with db.session() as s:
        mine = list(
            s.execute(
                select(Conversation, Participant)
                .join(Participant, Participant.conversation_id == Conversation.id)
                .where(Participant.user_id == user_id, Participant.archived.is_(archived))
                .order_by(Conversation.last_message_at.desc())
            ).all()
        )
        rows = []
        for c, p in mine:
            last = s.scalar(
                select(Message)
                .where(Message.conversation_id == c.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
            others = list(
                s.scalars(
                    select(Participant.user_id).where(
                        Participant.conversation_id == c.id, Participant.user_id != user_id
                    )
                )
            )
            unread = (
                last is not None
                and last.sender_id != user_id
                and (p.last_read_at is None or last.created_at > p.last_read_at)
            )
            rows.append(InboxRow(c, last, unread, others))
        return rows


def unread_count(db: Any, user_id: int) -> int:
    with db.session() as s:
        return (
            s.scalar(
                select(func.count())
                .select_from(Participant)
                .join(Conversation, Conversation.id == Participant.conversation_id)
                .where(
                    Participant.user_id == user_id,
                    Participant.archived.is_(False),
                    Conversation.last_message_at
                    > func.coalesce(Participant.last_read_at, datetime(1970, 1, 1)),
                )
            )
            or 0
        )


def sent_recently(db: Any, user_id: int, minutes: int = 60) -> int:
    with db.session() as s:
        return (
            s.scalar(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.sender_id == user_id,
                    Message.created_at > utcnow() - timedelta(minutes=minutes),
                )
            )
            or 0
        )
