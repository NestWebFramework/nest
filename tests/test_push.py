"""Push notifications: the message encrypted as RFC 8291 says (its own example, byte for
byte), the VAPID token signed with the site's key, only the browsers' push services
accepted, scheduling and the look again before sending (the hub's reminders: a bus late
moves its reminder), nothing kept once sent."""

import json
import textwrap
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from nest_push import store, webpush

from nest import create_app

# RFC 8291, Appendix A
RFC = {
    "plaintext": b"When I grow up, I want to be a watermelon",
    "auth": "BTBZMqHH6r4Tts7J_aSIgg",
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "ua_private": "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "body": "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
}


def private(b64: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(webpush.unb64(b64), "big"), ec.SECP256R1())


def decrypt(body: bytes, ua: ec.EllipticCurvePrivateKey, auth: str) -> bytes:
    """What the browser does (the receiving side of RFC 8291)."""
    salt, idlen = body[:16], body[20]
    as_public = body[21 : 21 + idlen]
    from cryptography.hazmat.primitives import serialization

    ua_public = ua.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = ua.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    )
    ikm = webpush._hkdf(
        webpush.unb64(auth), shared, b"WebPush: info\x00" + ua_public + as_public, 32
    )
    cek = webpush._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = webpush._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen :], None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_the_message_is_encrypted_as_rfc_8291s_own_example():
    body = webpush.encrypt(
        RFC["ua_public"],
        RFC["auth"],
        RFC["plaintext"],
        salt=webpush.unb64(RFC["salt"]),
        ephemeral=private(RFC["as_private"]),
    )
    assert webpush.b64(body) == RFC["body"]
    assert decrypt(body, private(RFC["ua_private"]), RFC["auth"]) == RFC["plaintext"]


def test_the_vapid_token_is_signed_with_the_sites_key(tmp_path):
    key = webpush.keys(tmp_path)
    assert webpush.keys(tmp_path).private_numbers() == key.private_numbers()  # kept, not remade
    assert (tmp_path / "data" / "push" / "vapid.pem").stat().st_mode & 0o077 == 0  # owner only
    header = webpush.vapid(key, "https://fcm.googleapis.com/fcm/send/abc", "mailto:a@example.com")
    token, k = header.removeprefix("vapid t=").split(", k=")
    assert k == webpush.public(key) and len(webpush.unb64(k)) == 65
    head, claims, sig = token.split(".")
    assert json.loads(webpush.unb64(claims))["aud"] == "https://fcm.googleapis.com"
    raw = webpush.unb64(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def browser(endpoint="https://fcm.googleapis.com/fcm/send/xyz"):
    ua = ec.generate_private_key(ec.SECP256R1())
    from cryptography.hazmat.primitives import serialization

    pub = ua.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = webpush.b64(b"0123456789abcdef")
    return ua, {"endpoint": endpoint, "keys": {"p256dh": webpush.b64(pub), "auth": auth}}


def test_only_the_browsers_push_services_are_accepted():
    _, sub = browser()
    assert store.valid(sub)["endpoint"].startswith("https://fcm.googleapis.com/")
    for bad in (
        "http://fcm.googleapis.com/x",
        "https://evil.example/x",
        "https://fcm.googleapis.com.evil.example/x",
        "https://127.0.0.1/x",
    ):
        assert store.valid({**sub, "endpoint": bad}) is None, bad
    assert store.valid({**sub, "keys": {"p256dh": "short", "auth": sub["keys"]["auth"]}}) is None


APP = """
module: {name: app, id: test.app.push, type: application, version: 0.1.0}
application: {title: App, port: 8000, theme: base, languages: [ro, en]}
modules:
  - {name: hub, route: /}
  - {name: push, route: /push, config: {contact: "mailto:ops@example.com"}}
bind:
  nest.db: {providers: [db-sqlite]}
"""


@pytest.fixture
def app(tmp_path, monkeypatch):
    from nest_hub import sources

    root = tmp_path / "app"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    board = {"rows": []}
    monkeypatch.setattr(sources, "fetch", lambda url, ttl: board if "/plecari" in url else None)
    with TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})) as c:
        c.board = board
        yield c


def headers(c):
    c.get("/")
    return {"X-CSRF-Token": c.cookies["nest_csrf"]}


class Ctx:
    def __init__(self, c):
        nest = c.app.state.nest
        self.host = nest.module_state["push"]["host"]


def test_a_reminder_moves_with_a_late_bus_and_is_gone_once_sent(app):
    from zoneinfo import ZoneInfo

    from nest_push import jobs

    local = ZoneInfo("Europe/Bucharest")
    ua, sub = browser()
    h = headers(app)
    assert app.get("/push/cheie").json()["key"]
    assert app.post("/push/abonare", json=sub, headers=h).status_code == 200
    assert (
        app.post(
            "/push/abonare", json={**sub, "endpoint": "https://evil.example/x"}, headers=h
        ).status_code
        == 400
    )
    leaves = (datetime.now(local) + timedelta(minutes=30)).replace(second=0, microsecond=0)
    at, day = leaves.strftime("%H:%M"), leaves.date().isoformat()
    row = {
        "at": at,
        "date": day,
        "line": "25",
        "to": "Snagov Nord",
        "live": None,
        "delay": None,
        "canceled": False,
    }
    app.board["rows"] = [row]
    ask = {
        "endpoint": sub["endpoint"],
        "kind": "city",
        "id": "cluj-napoca/sora",
        "place": "Sora",
        "line": "25",
        "to": "Snagov Nord",
        "date": day,
        "at": at,
        "before": 5,
    }
    r = app.post("/alerta", json=ask, headers=h)
    assert r.status_code == 200 and r.json()["at"] == (leaves - timedelta(minutes=5)).strftime(
        "%H:%M"
    )
    assert (
        app.post(
            "/alerta", json={**ask, "endpoint": "https://fcm.googleapis.com/other"}, headers=h
        ).status_code
        == 412
    )
    listed = app.post("/push/alerte", json={"endpoint": sub["endpoint"]}, headers=h).json()[
        "alerts"
    ]
    assert [a["ref"] for a in listed] == [r.json()["ref"]] and "Sora" in listed[0]["body"]

    db = app.app.state.nest.bindings.get("nest.db")
    from nest_push.models import Job, Subscription

    def make_due():
        with db.session() as s, s.begin():
            for j in s.query(Job):
                j.due = store.now() - timedelta(seconds=1)

    sent = []

    def post(endpoint, body, hdrs):
        sent.append((endpoint, body, hdrs))
        return 201

    # the bus is 8 minutes late: the reminder moves, nothing is sent yet
    row["live"] = (leaves + timedelta(minutes=8)).strftime("%H:%M")
    row["delay"] = 8
    make_due()
    assert jobs.send(Ctx(app), post=post).startswith("0 sent, 1 moved")
    with db.session() as s:
        due = s.query(Job).one().due.replace(tzinfo=UTC)
    assert abs(due - (leaves + timedelta(minutes=3))) < timedelta(seconds=5)
    # its time comes (the bus, still late, now 3 minutes away): sent, with the live time
    row["live"] = (datetime.now(local) + timedelta(minutes=3)).strftime("%H:%M")
    make_due()
    assert jobs.send(Ctx(app), post=post).startswith("1 sent")
    endpoint, body, hdrs = sent[0]
    assert endpoint == sub["endpoint"] and hdrs["Content-Encoding"] == "aes128gcm"
    assert hdrs["Authorization"].startswith("vapid t=")
    said = json.loads(decrypt(body, ua, sub["keys"]["auth"]))
    assert (
        "25 → Snagov Nord" in said["title"]
        and row["live"] in said["body"]
        and "8 min" in said["body"]
    )
    assert said["url"] == "/loc/city/cluj-napoca/sora"
    with db.session() as s:
        assert s.query(Job).count() == 0  # nothing kept once sent
        assert s.query(Subscription).count() == 1


def test_a_gone_browser_is_forgotten_and_a_cancelled_run_says_so(app):
    from nest_push import jobs
    from nest_push.models import Job, Subscription

    ua, sub = browser()
    h = headers(app)
    app.post("/push/abonare", json=sub, headers=h)
    from zoneinfo import ZoneInfo

    leaves = (datetime.now(ZoneInfo("Europe/Bucharest")) + timedelta(minutes=3)).replace(
        second=0, microsecond=0
    )
    at, day = leaves.strftime("%H:%M"), leaves.date().isoformat()
    app.board["rows"] = [
        {"at": at, "date": day, "line": "IR 1832", "to": "Dej Călători", "canceled": True}
    ]
    ask = {
        "endpoint": sub["endpoint"],
        "kind": "train",
        "id": "cluj-napoca",
        "place": "Cluj Napoca",
        "line": "IR 1832",
        "to": "Dej Călători",
        "date": day,
        "at": at,
        "before": 15,
    }
    assert app.post("/alerta", json=ask, headers=h).status_code == 200
    db = app.app.state.nest.bindings.get("nest.db")
    with db.session() as s, s.begin():
        for j in s.query(Job):
            j.due = store.now() - timedelta(seconds=1)
    sent = []
    assert jobs.send(Ctx(app), post=lambda e, b, hd: sent.append(b) or 201).startswith("1 sent")
    assert "Anulat" in json.loads(decrypt(sent[0], ua, sub["keys"]["auth"]))["body"]
    assert app.post("/alerta", json=ask, headers=h).status_code == 200
    with db.session() as s, s.begin():
        for j in s.query(Job):
            j.due = store.now() - timedelta(seconds=1)
    jobs.send(Ctx(app), post=lambda e, b, hd: 410)  # the push service: gone
    with db.session() as s:
        assert s.query(Subscription).count() == 0 and s.query(Job).count() == 0
    assert app.post("/alerta", json={**ask, "date": "2020-01-01"}, headers=h).status_code == 400
