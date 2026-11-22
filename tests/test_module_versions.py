"""Module versions chosen on a running site (nest.versions, nest.overlay): a module added
from a registry, updated, taken back to an older version (its migrations down), a change
that cannot start undone, and what a version needs checked before anything changes.

A small registry is served here over HTTP (the API nest.remote reads), with real wheels
of a "demo" module; every change runs as the admin panel runs it: ``nest modules <app>
version …`` in a process of its own."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

DEMO_INIT = """
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

VERSION = "{v}"


def setup(host):
    {fail}
    router = APIRouter()

    @router.get("/")
    def page():
        return PlainTextResponse("demo " + VERSION)

    host.mount(router)
"""

MIGRATION_1 = '''
"""demo: its items

Revision ID: demo_0001
"""
import sqlalchemy as sa
from alembic import op

revision = "demo_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("demo_item", sa.Column("id", sa.Integer(), primary_key=True))


def downgrade():
    op.drop_table("demo_item")
'''

MIGRATION_2 = '''
"""demo: a note on each item

Revision ID: demo_0002
"""
import sqlalchemy as sa
from alembic import op

revision = "demo_0002"
down_revision = "demo_0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("demo_item") as batch:
        batch.add_column(sa.Column("note", sa.String(80), nullable=True))


def downgrade():
    with op.batch_alter_table("demo_item") as batch:
        batch.drop_column("note")
'''


def wheel(version: str, *, migrations: int = 1, fail: bool = False, core: str = "") -> bytes:
    """A real wheel of the demo module at ``version``."""
    files = {
        "nest_demo/__init__.py": DEMO_INIT.format(
            v=version, fail='raise RuntimeError("broken on purpose")' if fail else "pass"
        ),
        "nest_demo/module.yml": textwrap.dedent(f"""
            module: {{name: demo, id: test.module.demo, type: module, version: {version}, title: Demo}}
            main: nest_demo
            requires: {{interfaces: [nest.db]}}
            deps: {{db: ">=0.2"}}
            db: {{migrations: migrations}}
        """),
        "nest_demo/migrations/versions/0001_demo.py": MIGRATION_1,
    }
    if migrations >= 2:
        files["nest_demo/migrations/versions/0002_demo.py"] = MIGRATION_2
    info = f"nest_demo-{version}.dist-info"
    requires = f"Requires-Dist: nest-core{core}\n"
    files[f"{info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: nest-demo\nVersion: {version}\n{requires}"
    )
    files[f"{info}/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    files[f"{info}/entry_points.txt"] = "[nest.modules]\ndemo = nest_demo\n"
    files[f"{info}/RECORD"] = "".join(f"{name},,\n" for name in files) + f"{info}/RECORD,,\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


class Registry:
    """The registry's two addresses nest.versions asks: a package's page, a file."""

    def __init__(self) -> None:
        self.wheels: dict[str, bytes] = {}
        self.lie: set[str] = set()  # versions whose listed sha256 is not their file's
        handler = self._handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def add(self, version: str, body: bytes) -> None:
        self.wheels[version] = body

    def detail(self) -> dict:
        files = []
        for v, body in self.wheels.items():
            sha = hashlib.sha256(body).hexdigest()
            files.append(
                {
                    "filename": f"nest_demo-{v}-py3-none-any.whl",
                    "sha256": "0" * 64 if v in self.lie else sha,
                    "kind": "wheel",
                    "version": v,
                    "signature": None,
                    "key": None,
                }
            )
        return {
            "name": "demo",
            "dist": "nest-demo",
            "files": files,
            "releases": [{"version": v, "nest": None, "yanked": False} for v in self.wheels],
        }

    def _handler(self):
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):  # noqa: N802
                if self.path == "/api/v1/packages/demo":
                    body = json.dumps(registry.detail()).encode()
                    kind = "application/json"
                elif self.path.startswith("/files/"):
                    name = self.path.rsplit("/", 1)[1]
                    version = name.split("-")[1]
                    body, kind = registry.wheels[version], "application/octet-stream"
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


APP = """
module: {name: site, id: test.app.site, type: application, version: 0.1.0}
application: {title: Site, port: 8000, theme: base}
modules: []
bind:
  nest.db: {providers: [db-sqlite]}
"""


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    registry = Registry()
    env = {
        **os.environ,
        "NEST_APP_WORKSPACE": str(tmp_path / "ws"),
        "NEST_REGISTRY_URL": registry.url,
        "XDG_CONFIG_HOME": str(tmp_path / "config"),  # no credentials, no pinned keys
    }
    env.pop("VIRTUAL_ENV", None)
    yield root, registry, env, tmp_path / "ws"
    registry.server.shutdown()


def nest(root: Path, env: dict, *args: str) -> tuple[int, str]:
    code = "import sys\nfrom nest.cli import main\nraise SystemExit(main(sys.argv[1:]))\n"
    done = subprocess.run(
        [sys.executable, "-c", code, "modules", str(root), *args, "--no-reload"],
        env=env, capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip
    return done.returncode, done.stdout + done.stderr


def columns(ws: Path) -> list[str] | None:
    db = next(ws.rglob("*.sqlite*"), None) or next(ws.rglob("*.db"), None)
    assert db is not None, list(ws.rglob("*"))
    with sqlite3.connect(db) as conn:
        rows = conn.execute("PRAGMA table_info(demo_item)").fetchall()
        version = conn.execute("SELECT version_num FROM demo_alembic_version").fetchall()
    return [r[1] for r in rows], [v[0] for v in version]


def page(root: Path, env: dict) -> str:
    code = (
        "import sys\nfrom fastapi.testclient import TestClient\nfrom nest import create_app\n"
        "with TestClient(create_app(sys.argv[1])) as c:\n    print(c.get('/demo/').text)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code, str(root)], env={**env, "NEST_MIGRATE": "check"},
        capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    return done.stdout + done.stderr


def test_added_updated_and_taken_back_with_its_migrations(setup):
    root, registry, env, ws = setup
    registry.add("1.0.0", wheel("1.0.0"))
    registry.add("2.0.0", wheel("2.0.0", migrations=2))

    code, out = nest(root, env, "version", "demo=1.0.0")  # added from the registry
    assert code == 0, out
    assert "demo — → 1.0.0" in out and "backup:" in out
    pins = json.loads((ws / "packages" / "pins.json").read_text())
    assert pins["nest-demo"]["version"] == "1.0.0" and pins["nest-demo"]["base"] is None
    code, out = nest(root, env, "enable", "demo", "--route", "/demo")
    assert code == 0, out
    assert "demo 1.0.0" in page(root, env)
    assert columns(ws) == (["id"], ["demo_0001"])

    code, out = nest(root, env, "version", "demo=2.0.0")  # an update: migrated up
    assert code == 0, out
    assert "demo 1.0.0 → 2.0.0" in out
    assert columns(ws) == (["id", "note"], ["demo_0002"])
    assert "demo 2.0.0" in page(root, env)  # and it starts as production does (check)

    code, out = nest(root, env, "version", "demo=1.0.0")  # back: migrated down first
    assert code == 0, out
    assert "demo: migrations taken down to demo_0001" in out
    assert columns(ws) == (["id"], ["demo_0001"])
    assert "demo 1.0.0" in page(root, env)

    code, out = nest(root, env, "migrations", "demo")
    assert code == 0 and "● demo_0001" in out, out
    log = (ws / "data" / "modules.log").read_text().splitlines()
    assert sum('"versions"' in line and '"done"' in line for line in log) == 3


def test_a_version_that_cannot_start_is_undone(setup):
    root, registry, env, ws = setup
    registry.add("1.0.0", wheel("1.0.0"))
    registry.add("1.1.0", wheel("1.1.0", fail=True))
    assert nest(root, env, "version", "demo=1.0.0")[0] == 0
    assert nest(root, env, "enable", "demo", "--route", "/demo")[0] == 0

    code, out = nest(root, env, "version", "demo=1.1.0")
    assert code == 1 and "does not start with these versions" in out, out
    pins = json.loads((ws / "packages" / "pins.json").read_text())
    assert pins["nest-demo"]["version"] == "1.0.0"  # put back
    assert "demo 1.0.0" in page(root, env)


def test_what_a_version_needs_and_its_file_are_checked_before_anything_changes(setup):
    root, registry, env, ws = setup
    registry.add("1.0.0", wheel("1.0.0"))
    registry.add("3.0.0", wheel("3.0.0", core=">=99"))
    registry.add("4.0.0", wheel("4.0.0"))
    registry.lie.add("4.0.0")
    assert nest(root, env, "version", "demo=1.0.0")[0] == 0

    code, out = nest(root, env, "version", "demo=3.0.0")
    assert code == 1 and "needs nest-core>=99" in out, out
    code, out = nest(root, env, "version", "demo=4.0.0")
    assert code == 1 and "is not the file the registry lists" in out, out
    code, out = nest(root, env, "version", "demo=9.9.9")
    assert code == 1 and "has no version 9.9.9" in out, out
    code, out = nest(root, env, "version", "demo=1.0.0")
    assert code == 1 and "runs 1.0.0 already" in out, out
    pins = json.loads((ws / "packages" / "pins.json").read_text())
    assert pins["nest-demo"]["version"] == "1.0.0"
    assert not (ws / "packages" / ".staging").exists()


def test_each_start_fits_the_choices_to_the_image_it_runs(tmp_path, monkeypatch):
    """A site deployed with another image later: a newer image wins, an older one keeps
    the newer choice (its tables may be past what the image knows), and a choice that no
    longer fits the image's other packages is set aside, saying why."""
    from nest import overlay

    ws = tmp_path / "ws"

    def pin(dist, version, base, requires=()):
        folder = ws / "packages" / f"{dist}-{version}"
        info = folder / f"{dist.replace('-', '_')}-{version}.dist-info"
        info.mkdir(parents=True)
        lines = "".join(f"Requires-Dist: {r}\n" for r in requires)
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {dist}\nVersion: {version}\n{lines}"
        )
        return overlay.Pin(dist, version, dist.removeprefix("nest-"), base=base)

    image = {"nest-demo": "0.9.0", "nest-other": "1.0.0", "nest-uses": "2.0.0"}
    needs: list[tuple[str, str, str]] = []
    monkeypatch.setattr(overlay, "image_version", lambda dist, workspace: image.get(dist))
    monkeypatch.setattr(overlay, "_image_requirements", lambda workspace: needs)
    overlay.save_pins(ws, {"nest-demo": pin("nest-demo", "1.0.0", base="0.9.0")})
    used, aside, _ = overlay.check(ws)
    assert set(used) == {"nest-demo"} and not aside  # the image did not move

    image["nest-demo"] = "1.2.0"  # a newer image: it wins
    used, aside, _ = overlay.check(ws)
    assert not used and "the image has 1.2.0 now" in aside["nest-demo"][1]

    image["nest-demo"] = "0.9.5"  # an image older than the choice: the choice stays
    used, aside, rebased = overlay.check(ws)
    assert used["nest-demo"].version == "1.0.0" and rebased
    assert overlay.load_pins(ws)["nest-demo"].base == "0.9.5"  # over the image it runs now

    # a choice that needs more than the image now has
    overlay.save_pins(
        ws,
        {
            "nest-demo": overlay.load_pins(ws)["nest-demo"],
            "nest-other": pin("nest-other", "1.1.0", base="1.0.0", requires=["nest-uses>=3"]),
        },
    )
    used, aside, _ = overlay.check(ws)
    assert "nest-other" in aside and "needs nest-uses>=3" in aside["nest-other"][1]
    assert "nest-demo" in used

    # one the image's other packages no longer take
    needs.append(("nest-uses", "nest-demo", "nest-demo>=1.5"))
    used, aside, _ = overlay.check(ws)
    assert (
        "nest-demo" in aside
        and "the image's nest-uses needs nest-demo>=1.5" in aside["nest-demo"][1]
    )


def test_a_forked_worker_takes_the_versions_chosen_since_its_master_loaded(tmp_path, monkeypatch):
    """nest serve's workers are forked from the master: one renewed after max_requests, or
    made when the master missed its reload, still imports what pins.json says now, never
    the code the master had (a site answering one version, then the other)."""
    import importlib
    import os

    from nest import overlay

    ws = tmp_path / "ws"
    image = tmp_path / "image"
    (image / "nest_forktest").mkdir(parents=True)
    (image / "nest_forktest" / "__init__.py").write_text('VERSION = "1"\n')
    pinned = ws / "packages" / "nest-forktest-2.0.0"
    (pinned / "nest_forktest").mkdir(parents=True)
    (pinned / "nest_forktest" / "__init__.py").write_text('VERSION = "2"\n')
    info = pinned / "nest_forktest-2.0.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: nest-forktest\nVersion: 2.0.0\n")
    (info / "RECORD").write_text("nest_forktest/__init__.py,,\n")
    monkeypatch.syspath_prepend(str(image))
    monkeypatch.setattr(overlay, "_loaded", {})
    monkeypatch.setattr(overlay, "_owner", {})
    chosen: dict = {}
    monkeypatch.setattr(overlay, "check", lambda workspace: (dict(chosen), {}, {}))
    try:
        overlay.activate(ws)  # the master, nothing chosen yet
        assert importlib.import_module("nest_forktest").VERSION == "1"
        chosen["nest-forktest"] = overlay.Pin("nest-forktest", "2.0.0", "forktest")
        assert overlay.activate(ws) == []  # the same process: never mixes versions
        assert importlib.import_module("nest_forktest").VERSION == "1"
        key = str(ws.resolve())
        overlay._owner[key] = os.getpid() + 1  # as a fork sees it: loaded by its parent
        assert overlay.activate(ws) == ["nest-forktest==2.0.0"]
        assert importlib.import_module("nest_forktest").VERSION == "2"
    finally:
        sys.modules.pop("nest_forktest", None)
        for p in list(sys.path):
            if str(ws) in p:
                sys.path.remove(p)


def test_a_worker_reloads_through_its_master_never_alone(tmp_path, monkeypatch):
    """A change asked of a nest serve worker signals its parent, the master (a pid file
    may be stale or of another namespace); without it, no worker is made again alone."""
    import signal

    from nest import modules

    sent = []
    monkeypatch.setenv(modules.SERVE_MASTER, "4242")
    monkeypatch.setattr(modules.os, "getppid", lambda: 4242)
    monkeypatch.setattr(modules.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert modules.reload_running(tmp_path) is True
    assert sent == [(4242, signal.SIGHUP)]

    class Nest:
        workspace = tmp_path
        reloader = object()  # would make only this worker's application again

    monkeypatch.setattr(modules.os, "getppid", lambda: 1)  # its master is gone
    assert modules.reload_app(Nest()) == ""
