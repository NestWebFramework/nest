"""Accounts without email or password (the keys module): a new account and its key, the key
bringing the character back on another browser, adding a device by its 6 digits or link,
signing a device out, the day's limit of new accounts, the accounts that go."""

import re
import textwrap
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from nest import create_app

APP = """
module: {name: game, id: test.app.game, type: application, version: 0.1.0}
application: {title: Joc, port: 8000, theme: base, languages: [ro]}
modules:
  - {name: auth, route: /cont, core: true}
  - name: keys
    route: /intrare
    config: {play: /joc, after: /joc, new_accounts_per_day: 3}
bind:
  nest.db: {providers: [db-sqlite]}
"""


@pytest.fixture
def game(tmp_path):
    root = tmp_path / "game"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        c.app_ = app
        c.db = app.state.nest.bindings.get("nest.db")
        yield c


def browser(game):
    """Another browser on the same site: its own cookies."""
    other = TestClient(game.app_)
    other.__enter__()
    return other


def post(c, path, **data):
    c.get("/healthz")
    token = c.cookies.get("nest_csrf")
    return c.post(path, data={"csrf_token": token, **data}, follow_redirects=False)


def signed_in(c) -> bool:
    return c.get("/intrare/", follow_redirects=False).headers.get("location", "").endswith("/cont")


def test_a_new_account_its_key_and_coming_back_on_another_browser(game):
    page = game.get("/intrare/").text
    assert "Începe jocul" in page and "Am deja un personaj" in page and 'href="/joc"' in page
    made = post(game, "/intrare/nou", nume="Ion")
    assert made.status_code == 200 and "nest_session" in made.headers.get("set-cookie", "")
    code = re.search(r"data-key-code>([a-z2-9-]{24})<", made.text).group(1)
    assert f"/intrare/cheie#{code}" in made.text  # the code only after #
    assert signed_in(game)
    assert "Nu e salvată încă" in game.get("/intrare/cont").text
    post(game, "/intrare/cheie/salvata")
    assert "Salvată" in game.get("/intrare/cont").text
    other = browser(game)
    assert not signed_in(other)
    wrong = post(other, "/intrare/cheie", cod="aaaa-bbbb-cccc-dddd-eeee")
    assert wrong.status_code == 400 and "nu deschide niciun personaj" in wrong.text
    back = post(other, "/intrare/cheie", cod=code.upper().replace("-", " "))  # as typed
    assert back.status_code == 303 and back.headers["location"] == "/joc" and signed_in(other)
    # a new key: the old one stops working
    fresh = re.search(
        r"data-key-code>([a-z2-9-]{24})<", post(game, "/intrare/cheie/noua").text
    ).group(1)
    third = browser(game)
    assert post(third, "/intrare/cheie", cod=code).status_code == 400
    assert post(third, "/intrare/cheie", cod=fresh).status_code == 303
    # no password: the email form never opens it
    from nest_auth.sessions import authenticate

    assert authenticate(game.db, "", "") is None


def test_adding_a_device_by_its_digits_or_link_and_signing_one_out(game):
    post(game, "/intrare/nou")
    page = post(game, "/intrare/dispozitiv/nou").text
    digits = re.search(r"keys-digits\"><strong>(\d{3} \d{3})<", page).group(1)
    assert "<svg" in page and "/intrare/leaga/" in page
    phone = browser(game)
    assert post(phone, "/intrare/leaga", cod=digits).status_code == 303 and signed_in(phone)
    again = browser(game)
    assert post(again, "/intrare/leaga", cod=digits).status_code == 400  # once
    link = re.search(
        r'href="https?://[^"]+/intrare/leaga/([^"]+)"', post(game, "/intrare/dispozitiv/nou").text
    ).group(1)
    assert "Personajul tău te așteaptă" in again.get(f"/intrare/leaga/{link}").text  # asks first
    assert not signed_in(again)
    assert post(again, "/intrare/leaga", token=link).status_code == 303 and signed_in(again)
    account = game.get("/intrare/cont").text
    ids = re.findall(r"/intrare/dispozitiv/([0-9a-f]{64})/iesire", account)
    assert len(ids) == 3 and "acesta" in account
    from nest_auth import token_id

    here = token_id(game.cookies["nest_session"])
    for sid in ids:
        if sid != here:
            post(game, f"/intrare/dispozitiv/{sid}/iesire")
    assert signed_in(game) and not signed_in(phone) and not signed_in(again)


def test_codes_tried_and_new_accounts_are_limited(game):
    for _ in range(3):
        game.cookies.clear()
        assert post(game, "/intrare/nou").status_code == 200
    game.cookies.clear()
    assert post(game, "/intrare/nou").status_code == 429
    for _ in range(10):
        post(game, "/intrare/cheie", cod="aaaa-bbbb-cccc-dddd-eeee")
    assert post(game, "/intrare/cheie", cod="aaaa-bbbb-cccc-dddd-eeee").status_code == 429


def test_accounts_never_protected_go_after_two_weeks_all_after_a_year(game):
    from nest_auth.models import Session, User
    from nest_keys import service
    from nest_keys.models import utcnow

    kept, _ = service.start(game.db, "păstrat")
    lost, _ = service.start(game.db, "pierdut")
    old, _ = service.start(game.db, "vechi")
    service.mark_saved(game.db, kept.id)
    service.mark_saved(game.db, old.id)
    forgotten = []
    later = utcnow() + timedelta(days=15)
    assert service.cleanup(game.db, forgotten.append, now=later) == (1, 0)
    assert forgotten == [lost.id]
    much_later = utcnow() + timedelta(days=400)
    with game.db.session() as s, s.begin():
        s.add(
            Session(
                id="x" * 64,
                user_id=kept.id,
                expires_at=much_later,
                last_seen_at=much_later - timedelta(days=1),
            )
        )
    assert service.cleanup(game.db, forgotten.append, now=much_later) == (0, 1)
    with game.db.session() as s:
        assert {u.name for u in s.query(User)} == {"păstrat"}


# --- passkeys, with a software authenticator ------------------------------------------


class SoftKey:
    """A passkey authenticator in software: an ECDSA P-256 key, attestation "none", user
    verified, as a phone or Windows Hello answers the browser."""

    def __init__(self, rp_id="testserver", origin="http://testserver"):
        import os

        from cryptography.hazmat.primitives.asymmetric import ec

        self.rp_id, self.origin = rp_id, origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.count = 0
        self.user = None

    @staticmethod
    def b64(data: bytes) -> str:
        import base64

        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    @staticmethod
    def unb64(text: str) -> bytes:
        import base64

        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    def _client(self, kind, challenge):
        import json

        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}
        ).encode()

    def _auth_data(self, flags, extra=b""):
        import hashlib

        self.count += 1
        return (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([flags])
            + self.count.to_bytes(4, "big")
            + extra
        )

    def create(self, options):
        import cbor2

        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
        )
        attested = bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + cose
        auth = self._auth_data(
            0x45 | 0x18, attested
        )  # user present, verified, backed up; attested data
        self.user = options["user"]["id"]
        client = self._client("webauthn.create", options["challenge"])
        return {
            "id": self.b64(self.cred_id),
            "rawId": self.b64(self.cred_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": self.b64(client),
                "attestationObject": self.b64(
                    cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
                ),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options):
        import hashlib

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        auth = self._auth_data(0x05 | 0x18)  # present, verified, backed up
        client = self._client("webauthn.get", options["challenge"])
        signature = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": self.b64(self.cred_id),
            "rawId": self.b64(self.cred_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": self.b64(client),
                "authenticatorData": self.b64(auth),
                "signature": self.b64(signature),
                "userHandle": self.user,
            },
            "clientExtensionResults": {},
        }


def call(c, path, body=None, origin="http://testserver"):
    c.get("/healthz")
    return c.post(
        path,
        json=body or {},
        headers={"X-CSRF-Token": c.cookies.get("nest_csrf"), "Origin": origin},
        follow_redirects=False,
    )


def test_a_passkey_protects_the_character_and_signs_in_another_browser(game):
    post(game, "/intrare/nou", nume="Ion")
    soft = SoftKey()
    got = call(game, "/intrare/acces/inregistrare/optiuni").json()
    assert got["options"]["rp"]["id"] == "testserver"
    assert got["options"]["authenticatorSelection"]["residentKey"] == "required"
    assert got["options"]["authenticatorSelection"]["userVerification"] == "required"
    made = call(
        game,
        "/intrare/acces/inregistrare",
        {"ticket": got["ticket"], "credential": soft.create(got["options"])},
    )
    assert made.json() == {"ok": True}
    # the same ticket twice: refused (a challenge serves once)
    again = call(
        game,
        "/intrare/acces/inregistrare",
        {"ticket": got["ticket"], "credential": soft.create(got["options"])},
    )
    assert again.status_code == 400
    account = game.get("/intrare/cont").text
    assert "sincronizată în contul tău" in account and "/intrare/acces/" in account

    other = browser(game)
    opts = call(other, "/intrare/acces/optiuni").json()
    assert (
        opts["options"]["allowCredentials"] == []
        and opts["options"]["userVerification"] == "required"
    )
    entered = call(
        other, "/intrare/acces", {"ticket": opts["ticket"], "credential": soft.get(opts["options"])}
    )
    assert entered.json() == {"ok": True, "go": "/joc"} and signed_in(other)

    # another site's page (or a phishing copy) cannot use it: its origin is not this one
    third = browser(game)
    opts = call(third, "/intrare/acces/optiuni").json()
    assert (
        call(third, "/intrare/acces/optiuni", origin="https://elsewhere.example").status_code == 403
    )
    soft.origin = "https://elsewhere.example"
    refused = call(
        third, "/intrare/acces", {"ticket": opts["ticket"], "credential": soft.get(opts["options"])}
    )
    assert refused.status_code == 400 and not signed_in(third)
    soft.origin = "http://testserver"
    # a passkey nobody registered
    stranger = SoftKey()
    stranger.user = "eA"
    opts = call(third, "/intrare/acces/optiuni").json()
    unknown = call(
        third,
        "/intrare/acces",
        {"ticket": opts["ticket"], "credential": stranger.get(opts["options"])},
    )
    assert unknown.json()["why"] == "unknown"


def test_a_passkey_counts_as_protection_and_goes_with_its_account(game):
    from datetime import timedelta

    from nest_keys import passkeys, service
    from nest_keys.models import utcnow

    post(game, "/intrare/nou")
    soft = SoftKey()
    got = call(game, "/intrare/acces/inregistrare/optiuni").json()
    call(
        game,
        "/intrare/acces/inregistrare",
        {"ticket": got["ticket"], "credential": soft.create(got["options"])},
    )
    (user_id,) = passkeys.users_with(game.db)
    assert service.protected(game.db, user_id)  # key not saved, but a passkey
    assert service.cleanup(game.db, lambda uid: None, now=utcnow() + timedelta(days=30)) == (0, 0)
    assert service.cleanup(game.db, lambda uid: None, now=utcnow() + timedelta(days=400)) == (0, 1)
    assert passkeys.users_with(game.db) == set()


# --- a device's PIN --------------------------------------------------------------------


def idle(game, hours):
    """As if this browser had not been used for some hours."""
    from nest_auth import token_id
    from nest_keys import pins
    from nest_keys.models import DevicePin, utcnow

    sid = token_id(game.cookies["nest_session"])
    with game.db.session() as s, s.begin():
        s.get(DevicePin, sid).last_active_at = utcnow() - timedelta(hours=hours)
    pins.forget()


PAGE = {"Accept": "text/html"}


def test_a_device_pin_locks_it_when_idle_and_unlocks_only_it(game):
    post(game, "/intrare/nou")
    assert "Pune un PIN" in game.get("/intrare/cont").text
    said = lambda r: r.headers["location"].split("pin=")[-1].split("#")[0]  # noqa: E731
    assert said(post(game, "/intrare/dispozitiv/pin", pin="1234", din_nou="1234")) == "easy"
    assert said(post(game, "/intrare/dispozitiv/pin", pin="12", din_nou="12")) == "digits"
    assert said(post(game, "/intrare/dispozitiv/pin", pin="4826", din_nou="4827")) == "diferit"
    assert said(post(game, "/intrare/dispozitiv/pin", pin="4826", din_nou="4826")) == "ok"
    assert "Schimbă PIN-ul" in game.get("/intrare/cont").text
    idle(game, 2)
    assert (
        game.get("/intrare/cont", headers=PAGE, follow_redirects=False).status_code == 200
    )  # not yet
    idle(game, 13)
    page = game.get("/intrare/cont?x=1", headers=PAGE, follow_redirects=False)
    assert (
        page.status_code == 303
        and page.headers["location"] == "/intrare/pin?next=/intrare/cont%3Fx%3D1"
    )
    api = game.post("/intrare/acces/inregistrare/optiuni", follow_redirects=False)
    assert api.status_code == 401 and api.json()["locked"] is True
    # locked, it cannot set itself a new PIN either (that page is behind the lock)
    assert post(game, "/intrare/dispozitiv/pin", pin="5555", din_nou="5555").status_code in (
        303,
        401,
    )
    assert game.get("/intrare/cont", headers=PAGE, follow_redirects=False).status_code == 303
    wrong = post(game, "/intrare/pin", pin="0000", next="/intrare/cont")
    assert wrong.status_code == 400 and "PIN greșit" in wrong.text
    right = post(game, "/intrare/pin", pin="4826", next="/intrare/cont")
    assert right.status_code == 303 and right.headers["location"] == "/intrare/cont"
    assert game.get("/intrare/cont", headers=PAGE, follow_redirects=False).status_code == 200
    # another browser signed in by the key has no PIN: the PIN is this device's
    other = browser(game)
    assert not signed_in(other)


def test_wrong_pins_pause_then_sign_the_device_out(game):
    post(game, "/intrare/nou")
    post(game, "/intrare/dispozitiv/pin", pin="4826", din_nou="4826")
    idle(game, 13)
    for _ in range(4):
        assert "PIN greșit" in post(game, "/intrare/pin", pin="0000").text
    post(game, "/intrare/pin", pin="0000")  # the fifth: paused
    assert "Așteaptă 15 minute" in post(game, "/intrare/pin", pin="4826").text  # even the right one
    from nest_keys import pins
    from nest_keys.models import DevicePin

    with game.db.session() as s, s.begin():
        for row in s.query(DevicePin):
            row.locked_until = None
    pins.forget()
    for _ in range(4):
        post(game, "/intrare/pin", pin="0000")
    out = post(game, "/intrare/pin", pin="0000")  # the tenth
    assert out.status_code == 303 and "iesit=1" in out.headers["location"]
    assert not signed_in(game)


def test_a_forgotten_pin_signs_the_device_out_and_the_key_brings_it_back(game):
    made = post(game, "/intrare/nou")
    code = re.search(r"data-key-code>([a-z2-9-]{24})<", made.text).group(1)
    post(game, "/intrare/dispozitiv/pin", pin="4826", din_nou="4826")
    idle(game, 13)
    assert post(game, "/intrare/iesire").status_code == 303 and not signed_in(game)
    assert post(game, "/intrare/cheie", cod=code).status_code == 303 and signed_in(game)
    assert (
        game.get("/intrare/cont", headers=PAGE, follow_redirects=False).status_code == 200
    )  # no PIN now
