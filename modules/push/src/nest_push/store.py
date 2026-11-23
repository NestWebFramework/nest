"""The browsers' addresses and what waits for them: sealed under the site's key, found by a
hash of the endpoint, limited per address."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, func, select

from nest_push.models import Job, Subscription

# the browsers' push services: an address elsewhere is refused (the site would post to it)
SERVICES = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
    "push.apple.com",
    "notify.windows.com",
)


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def utc(when: datetime) -> datetime:
    return when.astimezone(UTC).replace(tzinfo=None) if when.tzinfo else when


def key_of(host: Any) -> bytes:
    return hashlib.sha256(f"push:{host.sign('push-subscriptions')}".encode()).digest()


def seal(key: bytes, value: Any) -> str:
    nonce = os.urandom(12)
    box = AESGCM(key).encrypt(nonce, json.dumps(value, separators=(",", ":")).encode(), b"push1")
    return base64.urlsafe_b64encode(nonce + box).decode()


def unseal(key: bytes, text: str) -> Any:
    try:
        raw = base64.urlsafe_b64decode(text)
        return json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], b"push1"))
    except Exception:  # noqa: BLE001 - not ours, or the key changed
        return None


def endpoint_key(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


def valid(sub: Any) -> dict[str, str] | None:
    """A browser's subscription (PushSubscription.toJSON()), checked: an https address of a
    known push service, keys of the right sizes."""
    if not isinstance(sub, dict):
        return None
    endpoint = str(sub.get("endpoint") or "")
    keys = sub.get("keys") if isinstance(sub.get("keys"), dict) else {}
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    u = urllib.parse.urlsplit(endpoint)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or len(endpoint) > 1000:
        return None
    if not any(host == s or host.endswith("." + s) for s in SERVICES):
        return None
    try:
        if len(base64.urlsafe_b64decode(p256dh + "==")) != 65:
            return None
        if len(base64.urlsafe_b64decode(auth + "==")) != 16:
            return None
    except Exception:  # noqa: BLE001
        return None
    return {"endpoint": endpoint, "p256dh": p256dh, "auth": auth}


def subscribe(db: Any, key: bytes, sub: dict[str, str]) -> int:
    k = endpoint_key(sub["endpoint"])
    with db.session() as s, s.begin():
        row = s.scalar(select(Subscription).where(Subscription.key == k))
        if row is None:
            row = Subscription(key=k, sealed=seal(key, sub), created=now(), used=now())
            s.add(row)
        else:  # the browser renewed its keys
            row.sealed, row.used = seal(key, sub), now()
        s.flush()
        return row.id


def unsubscribe(db: Any, endpoint: str) -> None:
    with db.session() as s, s.begin():
        s.execute(delete(Subscription).where(Subscription.key == endpoint_key(endpoint)))


def find(db: Any, endpoint: str) -> int | None:
    with db.session() as s:
        return s.scalar(select(Subscription.id).where(Subscription.key == endpoint_key(endpoint)))


def schedule(
    db: Any,
    key: bytes,
    endpoint: str,
    ref: str,
    due: datetime,
    message: dict[str, Any],
    data: dict[str, Any] | None = None,
    recheck: str = "",
    most: int = 20,
) -> str:
    """Schedules (or moves) the notification ``ref`` for this browser: "ok", "unknown" (no
    such address: subscribe first) or "full" (``most`` already waiting)."""
    sid = find(db, endpoint)
    if sid is None:
        return "unknown"
    with db.session() as s, s.begin():
        row = s.scalar(select(Job).where(Job.subscription_id == sid, Job.ref == ref[:200]))
        if row is None:
            waiting = s.scalar(select(func.count(Job.id)).where(Job.subscription_id == sid)) or 0
            if waiting >= most:
                return "full"
            row = Job(subscription_id=sid, ref=ref[:200], created=now())
            s.add(row)
        row.due, row.recheck, row.tries = utc(due), recheck, 0
        row.sealed = seal(key, {"message": message, "data": data or {}})
        sub = s.get(Subscription, sid)
        if sub is not None:
            sub.used = now()
    return "ok"


def waiting(db: Any, key: bytes, endpoint: str) -> list[dict[str, Any]]:
    """What waits for this browser: ref, when (UTC), the message and the module's data."""
    sid = find(db, endpoint)
    if sid is None:
        return []
    with db.session() as s:
        rows = list(s.scalars(select(Job).where(Job.subscription_id == sid).order_by(Job.due)))
    out = []
    for r in rows:
        inside = unseal(key, r.sealed) or {}
        out.append({"ref": r.ref, "due": r.due.replace(tzinfo=UTC), **inside})
    return out


def cancel(db: Any, endpoint: str, ref: str) -> bool:
    sid = find(db, endpoint)
    if sid is None:
        return False
    with db.session() as s, s.begin():
        done = s.execute(delete(Job).where(Job.subscription_id == sid, Job.ref == ref[:200]))
    return bool(done.rowcount)


def tidy(db: Any, forget_days: int) -> tuple[int, int]:
    """Deletes notifications more than 6 hours overdue, and addresses with nothing waiting
    and not used for ``forget_days``: (notifications, addresses)."""
    with db.session() as s, s.begin():
        late = s.execute(delete(Job).where(Job.due < now() - timedelta(hours=6))).rowcount
        busy = select(Job.subscription_id).distinct()
        gone = s.execute(
            delete(Subscription).where(
                Subscription.used < now() - timedelta(days=forget_days),
                Subscription.id.not_in(busy),
            )
        ).rowcount
    return late or 0, gone or 0
