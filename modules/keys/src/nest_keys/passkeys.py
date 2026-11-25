"""Passkeys (WebAuthn), through py_webauthn: register one on a signed-in account, sign in with
one (discoverable: no name asked, the device offers its passkeys), list and remove them.

Every ceremony's challenge is kept server-side for five minutes behind a random ticket the
page sends back, and used once. User verification is required: the device checks its owner
(fingerprint, face, its PIN or password) before it signs. The relying party is the site's own
host; the origin the browser reports must be that host.
"""

from __future__ import annotations

import json
import secrets
from datetime import timedelta
from typing import Any

import webauthn
from nest_auth import CurrentUser, active_user
from sqlalchemy import delete, select
from webauthn.helpers import bytes_to_base64url, parse_authentication_credential_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from nest_keys.models import Challenge, Passkey, utcnow
from nest_keys.service import digest

MINUTES = 5


class PasskeyError(ValueError):
    pass


def _keep(db: Any, challenge: bytes, purpose: str, user_id: int | None) -> str:
    ticket = secrets.token_urlsafe(24)
    now = utcnow()
    with db.session() as s, s.begin():
        s.execute(delete(Challenge).where(Challenge.expires_at < now))
        s.add(
            Challenge(
                id=digest(ticket),
                challenge=challenge,
                purpose=purpose,
                user_id=user_id,
                expires_at=now + timedelta(minutes=MINUTES),
            )
        )
    return ticket


def _take(db: Any, ticket: str, purpose: str) -> Challenge:
    with db.session() as s, s.begin():
        row = s.get(Challenge, digest(ticket or ""))
        if row is None:
            raise PasskeyError("expired")
        # a copy: the row itself is deleted (used once), and expunging it would undo that
        kept = Challenge(
            id=row.id,
            challenge=row.challenge,
            purpose=row.purpose,
            user_id=row.user_id,
            expires_at=row.expires_at,
        )
        s.delete(row)
    if kept.purpose != purpose or kept.expires_at < utcnow():
        raise PasskeyError("expired")
    return kept


def register_options(db: Any, user: CurrentUser, rp_id: str, rp_name: str, label: str) -> dict:
    """What the page hands navigator.credentials.create(), and the ticket to send back."""
    with db.session() as s:
        have = list(s.scalars(select(Passkey.id).where(Passkey.user_id == user.id)))
    from webauthn.helpers import base64url_to_bytes

    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=f"nest-user-{user.id}".encode(),
        user_name=label,
        user_display_name=label,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in have],
    )
    ticket = _keep(db, options.challenge, "register", user.id)
    return {"ticket": ticket, "options": json.loads(webauthn.options_to_json(options))}


def register(
    db: Any, user: CurrentUser, ticket: str, credential: Any, rp_id: str, origin: str, name: str
) -> Passkey:
    row = _take(db, ticket, "register")
    if row.user_id != user.id:
        raise PasskeyError("expired")
    try:
        found = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=row.challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except Exception as e:  # noqa: BLE001 - the library's own errors: refused, said plainly
        raise PasskeyError("refused") from e
    transports = []
    if isinstance(credential, dict):
        transports = [str(t) for t in (credential.get("response") or {}).get("transports") or []]
    key = Passkey(
        id=bytes_to_base64url(found.credential_id),
        user_id=user.id,
        public_key=found.credential_public_key,
        sign_count=found.sign_count,
        transports=",".join(transports)[:120],
        name=name[:120],
        synced=1 if found.credential_backed_up else 0,
        created_at=utcnow(),
    )
    with db.session() as s, s.begin():
        if s.get(Passkey, key.id) is not None:
            raise PasskeyError("known")
        s.add(key)
    return key


def enter_options(db: Any, rp_id: str) -> dict:
    """For signing in: no credentials named (the device offers its own for this site)."""
    options = webauthn.generate_authentication_options(
        rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED
    )
    ticket = _keep(db, options.challenge, "enter", None)
    return {"ticket": ticket, "options": json.loads(webauthn.options_to_json(options))}


def enter(db: Any, ticket: str, credential: Any, rp_id: str, origin: str) -> CurrentUser:
    row = _take(db, ticket, "enter")
    try:
        parsed = parse_authentication_credential_json(
            json.dumps(credential) if isinstance(credential, dict) else credential
        )
    except Exception as e:  # noqa: BLE001
        raise PasskeyError("refused") from e
    with db.session() as s:
        key = s.get(Passkey, parsed.id)
        if key is None:
            raise PasskeyError("unknown")
        s.expunge(key)
    try:
        found = webauthn.verify_authentication_response(
            credential=parsed,
            expected_challenge=row.challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=key.public_key,
            credential_current_sign_count=key.sign_count,
            require_user_verification=True,
        )
    except Exception as e:  # noqa: BLE001
        raise PasskeyError("refused") from e
    with db.session() as s, s.begin():
        stored = s.get(Passkey, key.id)
        stored.sign_count = found.new_sign_count
        stored.last_used_at = utcnow()
    user = active_user(db, key.user_id)
    if user is None:
        raise PasskeyError("unknown")
    return user


def of(db: Any, user_id: int) -> list[Passkey]:
    with db.session() as s:
        rows = list(
            s.scalars(
                select(Passkey).where(Passkey.user_id == user_id).order_by(Passkey.created_at)
            )
        )
        for r in rows:
            s.expunge(r)
        return rows


def users_with(db: Any) -> set[int]:
    with db.session() as s:
        return set(s.scalars(select(Passkey.user_id).distinct()))
