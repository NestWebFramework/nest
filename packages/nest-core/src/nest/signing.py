"""Signing what is published, and trusting who signed what is installed (Ed25519).

``nest keygen`` makes a key: the private half in ``~/.config/nest/keys/<name>.key``
(readable by its owner only), the public half printed, to be registered with the registry
(``--register``, or the Tokens page). ``nest publish`` signs each file it uploads with it:
the signature covers the file's name and its sha256, so it cannot be moved to another file.
The registry accepts a signature only from a key registered to the publishing account,
and shows it beside the file.

``nest trust <package|*> <key>`` pins the keys a package (or every package) must be signed
by; installing from the registry then refuses a file that is unsigned or signed by any
other key, and checks that the sha256 uv.lock pins is the signed one.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

import yaml


class SigningError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "nest"


def message(filename: str, sha256: str) -> bytes:
    """What a signature covers: the file's name and its content's sha256."""
    return f"nest-file\n{filename}\n{sha256.lower()}".encode()


def fingerprint(public: str) -> str:
    """A short name for a public key (the first 16 hex digits of its sha256)."""
    return hashlib.sha256(base64.b64decode(public)).hexdigest()[:16]


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def public_of(private_pem: bytes) -> str:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

    key = serialization.load_pem_private_key(private_pem, password=None)
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64(raw)


def keygen(name: str = "default", *, force: bool = False) -> tuple[Path, str]:
    """A new key: where its private half is kept, and its public half (base64)."""
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415

    if not name.replace("-", "").replace("_", "").isalnum():
        raise SigningError([f"'{name}' is not a key name (letters, digits, - and _)"])
    path = config_dir() / "keys" / f"{name}.key"
    if path.exists() and not force:
        raise SigningError([f"{path} exists; --force makes a new one (the old key is lost)"])
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pem = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(pem)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path, public_of(pem)


def signing_key(environ: Any = None) -> bytes | None:
    """The key ``nest publish`` signs with: $NEST_SIGNING_KEY (the PEM, for CI), else the
    file $NEST_SIGNING_KEY_FILE, else ~/.config/nest/keys/default.key; None without one."""
    environ = os.environ if environ is None else environ
    if environ.get("NEST_SIGNING_KEY"):
        return environ["NEST_SIGNING_KEY"].encode()
    path = Path(environ.get("NEST_SIGNING_KEY_FILE") or config_dir() / "keys" / "default.key")
    return path.read_bytes() if path.is_file() else None


def sign(private_pem: bytes, filename: str, sha256: str) -> str:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

    key = serialization.load_pem_private_key(private_pem, password=None)
    return _b64(key.sign(message(filename, sha256)))


def verify(public: str, filename: str, sha256: str, signature: str) -> bool:
    from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: PLC0415

    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public))
        key.verify(base64.b64decode(signature), message(filename, sha256))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def valid_public(public: str) -> bool:
    try:
        return len(base64.b64decode(public, validate=True)) == 32
    except (ValueError, TypeError):
        return False


# --- what this machine trusts ------------------------------------------------------------------


def trust_file() -> Path:
    return config_dir() / "trust.yml"


def trusted() -> dict[str, list[str]]:
    """The pinned keys, by package ("*": every package)."""
    file = trust_file()
    if not file.is_file():
        return {}
    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    pins = raw.get("packages") if isinstance(raw, dict) else None
    return {str(k): [str(x) for x in v] for k, v in (pins or {}).items()}


def trust(package: str, public: str) -> None:
    if not valid_public(public):
        raise SigningError(["not an Ed25519 public key (base64, 32 bytes)"])
    pins = trusted()
    keys = pins.setdefault(package, [])
    if public not in keys:
        keys.append(public)
    _save(pins)


def untrust(package: str, public: str | None = None) -> None:
    pins = trusted()
    if public is None:
        pins.pop(package, None)
    else:
        pins[package] = [k for k in pins.get(package, []) if k != public]
        if not pins[package]:
            pins.pop(package)
    _save(pins)


def _save(pins: dict[str, list[str]]) -> None:
    file = trust_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump({"packages": pins}, sort_keys=True), encoding="utf-8")
    os.replace(tmp, file)


def pins_for(package: str) -> list[str]:
    pins = trusted()
    return [*pins.get(package, []), *pins.get("*", [])]


def check(package: str, file: dict[str, Any]) -> list[str]:
    """What a pinned package's file lacks: a signature, by a pinned key, that holds."""
    pins = pins_for(package)
    if not pins:
        return []
    signature, signer = file.get("signature"), file.get("key")
    if not signature or not signer:
        return [f"{file.get('filename')} is not signed, and {package} must be (nest trust)"]
    if signer not in pins:
        return [
            f"{file.get('filename')} is signed by {fingerprint(signer)}, a key {package} is not trusted with"
        ]
    if not verify(signer, file["filename"], file["sha256"], signature):
        return [f"{file.get('filename')}'s signature does not hold"]
    return []
