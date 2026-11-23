"""Web Push, from the standards, with the cryptography package only:

- the site's key pair (VAPID, RFC 8292): an EC P-256 key in the workspace; each request
  carries a short signed token (ES256 JWT) and the public key;
- the message encrypted for the browser (RFC 8291, "aes128gcm" of RFC 8188): an ephemeral
  key agreed with the browser's (p256dh) and its auth secret, one record.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RECORD = 4096


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def keys(workspace: Path) -> ec.EllipticCurvePrivateKey:
    """The site's VAPID key: made once, kept in the workspace (only its owner may read it)."""
    path = Path(workspace) / "data" / "push" / "vapid.pem"
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(pem)
    tmp.chmod(0o600)
    try:
        os.link(tmp, path)  # only the first worker's key wins; the others read it
    except FileExistsError:
        pass
    finally:
        tmp.unlink(missing_ok=True)
    return keys(workspace)


def public(key: ec.EllipticCurvePrivateKey) -> str:
    """The public key as browsers want it (applicationServerKey): uncompressed, base64url."""
    raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64(raw)


def vapid(key: ec.EllipticCurvePrivateKey, endpoint: str, contact: str) -> str:
    """The Authorization header for a push service: a token for its origin, 12 hours."""
    u = urllib.parse.urlsplit(endpoint)
    header = b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = {
        "aud": f"{u.scheme}://{u.netloc}",
        "exp": int(time.time()) + 12 * 3600,
        "sub": contact,
    }
    body = b64(json.dumps(claims, separators=(",", ":")).encode())
    der = key.sign(f"{header}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    token = f"{header}.{body}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={token}, k={public(key)}"


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(
    p256dh: str,
    auth: str,
    plaintext: bytes,
    salt: bytes | None = None,
    ephemeral: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """The body for a push service: aes128gcm, one record, for the browser's keys."""
    ua_public = unb64(p256dh)
    auth_secret = unb64(auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_key = ephemeral or ec.generate_private_key(ec.SECP256R1())
    as_public = as_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = as_key.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    record = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)  # \x02: the last record
    header = salt + RECORD.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + record


def send(
    key: ec.EllipticCurvePrivateKey,
    sub: dict[str, Any],
    message: dict[str, Any],
    contact: str,
    ttl: int = 3600,
    post: Any = None,
) -> int:
    """Sends one message; the push service's status (201: taken; 404/410: the address is
    gone; 0: it did not answer)."""
    body = encrypt(sub["p256dh"], sub["auth"], json.dumps(message, ensure_ascii=False).encode())
    headers = {
        "Authorization": vapid(key, sub["endpoint"], contact),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": "high",
    }
    if post is not None:
        return post(sub["endpoint"], body, headers)
    req = urllib.request.Request(sub["endpoint"], data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - the browser's push service
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001 - the push service did not answer: tried again later
        return 0
