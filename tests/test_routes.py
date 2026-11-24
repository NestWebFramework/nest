"""Calls between sites side by side (NEST_LOCAL_ROUTES): straight to the other's container,
saying the public host, so the answer and its links are the public ones; the public address
when the container is not there."""

import contextlib
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from nest import routes


def test_the_table_and_what_goes_local():
    env = {
        routes.ENV: "gari.ro=http://nest-gari:8000, transportul.ro=http://nest-transportul:8000/, bad=ftp://x, x.ro=http://h:1/path"
    }
    assert routes.table(env) == {
        "gari.ro": "http://nest-gari:8000",
        "transportul.ro": "http://nest-transportul:8000",
    }
    assert routes.local("https://gari.ro/cfr/api/v1/aproape?lat=1&lon=2", env) == (
        "http://nest-gari:8000/cfr/api/v1/aproape?lat=1&lon=2",
        "gari.ro",
    )
    assert routes.local("https://www.gari.ro/x", env) is None  # only the hosts listed
    assert routes.local("https://gari.ro:8443/x", env) is None  # another port: not that site
    assert routes.local("https://evil.example/x", env) is None


class Echo(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps(
            {
                "host": self.headers["Host"],
                "proto": self.headers["X-Forwarded-Proto"],
                "path": self.path,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_a_listed_site_is_asked_locally_and_a_missing_one_from_outside(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    monkeypatch.setenv(
        routes.ENV, f"gari.ro=http://127.0.0.1:{port}, transportul.ro=http://127.0.0.1:1"
    )
    req = urllib.request.Request(
        "https://gari.ro/cfr/api/v1/aproape?lat=1", headers={"Accept": "application/json"}
    )
    with routes.urlopen(req, timeout=5) as r:
        said = json.loads(r.read())
    assert said == {"host": "gari.ro", "proto": "https", "path": "/cfr/api/v1/aproape?lat=1"}
    asked = []

    def public(request, timeout=0):
        asked.append(request.full_url if hasattr(request, "full_url") else request)
        raise OSError("no network in the tests")

    real = urllib.request.urlopen

    def fake(request, timeout=0):
        url = request.full_url if hasattr(request, "full_url") else request
        if url.startswith("https://transportul.ro"):
            return public(request, timeout)
        return real(request, timeout=timeout)

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with contextlib.suppress(OSError):
        routes.urlopen("https://transportul.ro/api/v1/aproape", timeout=2)  # nothing on port 1
    assert asked == ["https://transportul.ro/api/v1/aproape"]  # then the public address
    server.shutdown()
