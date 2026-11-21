"""Signing (nest.signing): keys kept for their owner only, signatures bound to a file's name
and content, pinned keys; and the environment choosing among a binding's providers."""

import os

import pytest

from nest.signing import (
    SigningError,
    check,
    fingerprint,
    keygen,
    sign,
    trust,
    trusted,
    untrust,
    verify,
)


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def test_a_key_is_its_owners_alone_and_signs_a_file_by_name_and_content():
    path, public = keygen("laptop")
    assert (
        oct(os.stat(path).st_mode)[-3:] == "600" and oct(os.stat(path.parent).st_mode)[-3:] == "700"
    )
    with pytest.raises(SigningError, match="exists"):
        keygen("laptop")
    sig = sign(path.read_bytes(), "a-1.0.whl", "ab" * 32)
    assert verify(public, "a-1.0.whl", "ab" * 32, sig)
    assert not verify(public, "a-1.0.whl", "cd" * 32, sig)  # other content
    assert not verify(public, "b-1.0.whl", "ab" * 32, sig)  # other file
    assert len(fingerprint(public)) == 16


def test_pinned_keys_decide_what_a_package_may_be_signed_by():
    path, public = keygen()
    _, other = keygen("other")
    file = {
        "filename": "a-1.0.whl",
        "sha256": "ab" * 32,
        "signature": sign(path.read_bytes(), "a-1.0.whl", "ab" * 32),
        "key": public,
    }
    assert check("a", file) == []  # nothing pinned: anything goes
    trust("a", other)
    assert "not trusted with" in check("a", file)[0]
    trust("*", public)
    assert check("a", file) == []  # every package may be signed by it
    assert "is not signed" in check("b", {"filename": "b.whl", "sha256": "x"})[0]
    untrust("*")
    untrust("a")
    assert trusted() == {}
    with pytest.raises(SigningError, match="not an Ed25519"):
        trust("a", "not-a-key")


def test_the_environment_chooses_among_a_bindings_alternatives(tmp_path):
    from nest import create_app  # noqa: PLC0415

    root = tmp_path / "app"
    root.mkdir()
    (root / "module.yml").write_text(
        "module: {name: app, id: test.app.app, type: application, version: 0.1.0}\n"
        "application: {title: App, port: 8000, theme: base}\n"
        "bind:\n  nest.cache: {providers: [cache-memory], alternatives: [redis]}\n",
        encoding="utf-8",
    )
    env = {"NEST_APP_WORKSPACE": str(tmp_path / "ws")}
    nest = create_app(root, environ=env).state.nest
    assert [p.name for p in nest.bindings.providers()] == [
        "cache-memory"
    ]  # the alternative is not made
    chosen = create_app(
        root,
        environ={
            **env,
            "NEST_BIND__NEST_CACHE": "redis",
            "NEST_APP__REDIS__URL": "redis://127.0.0.1:1/0",
        },
    ).state.nest
    assert [p.name for p in chosen.bindings.providers()] == ["redis"]
    with pytest.raises(Exception, match="nest.cache may use cache-memory, redis"):
        create_app(root, environ={**env, "NEST_BIND__NEST_CACHE": "db-sqlite"})


def test_s3_storage_keeps_keys_under_the_applications_prefix():
    import io  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415
    from types import SimpleNamespace  # noqa: PLC0415

    from nest_storage import StorageError  # noqa: PLC0415
    from nest_storage_s3 import create  # noqa: PLC0415

    class Fake:
        def __init__(self):
            self.objects = {}

        def bucket_exists(self, bucket):
            return False

        def make_bucket(self, bucket):
            self.made = bucket

        def put_object(self, bucket, name, stream, length, content_type="", part_size=0):
            self.objects[name] = (stream.read(), content_type)

        def stat_object(self, bucket, name):
            if name not in self.objects:
                raise type("E", (Exception,), {"code": "NoSuchKey"})()
            data, kind = self.objects[name]
            return SimpleNamespace(
                size=len(data), last_modified=datetime.now(UTC), content_type=kind
            )

        def get_object(self, bucket, name):
            if name not in self.objects:
                raise type("E", (Exception,), {"code": "NoSuchKey"})()
            body = io.BytesIO(self.objects[name][0])
            body.release_conn = lambda: None
            return body

        def remove_object(self, bucket, name):
            self.objects.pop(name, None)

        def list_objects(self, bucket, prefix="", recursive=True):
            return [SimpleNamespace(object_name=n) for n in self.objects if n.startswith(prefix)]

    fake = Fake()
    settings = SimpleNamespace(
        endpoint="x",
        bucket="b",
        access_key="a",
        secret_key="s",
        secure=True,
        region="",
        prefix="",
        create_bucket=True,
    )
    store = create(settings, SimpleNamespace(app="registry"), client=fake)
    assert fake.made == "b"
    st = store.put("files/a.whl", b"wheel", "application/octet-stream")
    assert st.size == 5 and "registry/files/a.whl" in fake.objects
    with store.open("files/a.whl") as f:
        assert f.read() == b"wheel"
    assert list(store.keys("files")) == ["files/a.whl"]
    assert store.stat("nothing") is None and store.local_path("files/a.whl") is None
    with pytest.raises(FileNotFoundError):
        store.open("nothing")
    with pytest.raises(StorageError):
        store.put("../escape", b"x")
    store.delete("files/a.whl")
    assert store.stat("files/a.whl") is None
