"""Cookies and consent: the notice asks only for what needs consent, in plain words; the
choice (all, only the essential, or chosen) holds for every module (Google Analytics loads
only once allowed); a new cookie that needs consent asks again; the cookies page lists all."""

import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_consent.cookies import COOKIE, Choice, Cookie, State, fingerprint

from nest import create_app

APP = """
module: {{name: site, id: test.app.site, type: application, version: 0.1.0}}
application: {{title: Site, port: 8000, theme: base, languages: [ro, en]}}
modules:
  - {{name: consent, route: /cookies}}
  - name: seo
    config: {{google_analytics: "{ga}"}}
bind:
  nest.db: {{providers: [db-sqlite]}}
"""


def make(tmp_path, ga=""):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP.format(ga=ga)), encoding="utf-8")
    return TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")}))


@pytest.fixture
def site(tmp_path):
    with make(tmp_path, ga="G-TEST1234") as c:
        yield c


def choose(c, **data):
    c.get("/cookies/")
    return c.post(
        "/cookies/alege",
        data={"csrf_token": c.cookies["nest_csrf"], **data},
        follow_redirects=False,
    )


def test_with_nothing_to_ask_there_is_no_notice(tmp_path):
    with make(tmp_path) as c:
        page = c.get("/cookies/").text
        assert "nest-consent-bar" not in page
        assert "nest_csrf" in page and "nimic de ales" in page  # the essential ones, listed


def test_the_notice_asks_plainly_and_analytics_waits_for_it(site):
    page = site.get("/cookies/").text
    bar = page[page.index("nest-consent-bar") : page.index("</aside>")]
    assert "ca să vedem ce pagini sunt utile" in bar  # what it is for, in plain words
    assert "Google" not in bar and "urmăr" not in bar  # no provider, no "tracking" in the notice
    assert "analytics.js" not in page  # nothing of Google's before the visitor agrees
    assert "Google Analytics" in page  # the page itself says who sets each cookie
    assert "_ga_TEST1234" in page


def test_accepting_all_loads_analytics_and_ends_the_notice(site):
    r = choose(site, action="all", back="/cookies/")
    assert r.status_code == 303 and r.headers["location"] == "/cookies/"
    assert "statistics" in site.cookies[COOKIE]
    page = site.get("/cookies/").text
    assert (
        "nest-consent-bar" not in page and "analytics.js" in page and 'data-consent="given"' in page
    )


def test_only_the_essential_keeps_analytics_out(site):
    choose(site, action="necessary")
    page = site.get("/cookies/").text
    assert "nest-consent-bar" not in page and "analytics.js" not in page


def test_a_choice_purpose_by_purpose(site):
    choose(site, action="choose", purpose="statistics")
    assert "analytics.js" in site.get("/cookies/").text
    choose(site, action="choose")  # nothing ticked: the visitor changed their mind
    assert "analytics.js" not in site.get("/cookies/").text


def test_a_new_cookie_that_needs_consent_asks_again(site):
    site.cookies.set(COOKIE, Choice("old-print", {"statistics"}).encode())
    assert "nest-consent-bar" in site.get("/cookies/").text


def test_it_never_sends_the_visitor_elsewhere(site):
    r = choose(site, action="all", back="https://evil.example/")
    assert r.headers["location"] == "/cookies"
    r = choose(site, action="all", back="//evil.example/")
    assert r.headers["location"] == "/cookies"


def test_services_of_one_purpose_may_be_refused_one_by_one():
    cookies = [
        Cookie("_ga", "statistics", "2 years", "", "seo", "Google Analytics", "google-analytics"),
        Cookie("_pk", "statistics", "1 year", "", "other", "Matomo", "matomo"),
        Cookie("nest_csrf", "necessary", "session", "", "nest"),
    ]
    fp = fingerprint(cookies)
    st = State(cookies, Choice(fp, {"statistics"}, {"matomo"}), fp)
    assert st.allowed("statistics", "google-analytics") and not st.allowed("statistics", "matomo")
    assert st.allowed("necessary") and not st.allowed("marketing")
    assert [k for k, _ in st.services("statistics")] == ["google-analytics", "matomo"]
    assert Choice.decode(Choice(fp, {"statistics"}, {"matomo"}).encode()).refused == {"matomo"}
    assert fingerprint([c for c in cookies if c.purpose == "necessary"]) == ""  # nothing to ask
