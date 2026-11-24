"""Ratings: stars, useful-or-not and up/down, one vote per visitor and subject (changeable,
taken back with the same button), the same visitor known for a day though it cleared its
cookie, a vote only on a subject a page offered (signed), an average only from enough votes,
the stars for search engines only where asked, the admin's tools."""

import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_rating import service

from nest import create_app

APP = """
module: {name: site, id: test.app.rating, type: application, version: 0.1.0}
application: {title: Site, port: 8000, theme: base, languages: [ro, en]}
modules:
  - {name: rating, route: /nota, config: {min_votes: 3, per_minute: 50}}
  - {name: consent, route: /cookies}
bind:
  nest.db: {providers: [db-sqlite]}
"""


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    with TestClient(create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})) as c:
        c.db = c.app.state.nest.bindings.get("nest.db")
        yield c


def form(c, subject, kind, value):
    nest = c.app.state.nest
    c.get("/cookies/")  # the CSRF cookie
    return {
        "subject": subject,
        "kind": kind,
        "value": str(value),
        "sig": service.sign(nest.secret, subject, kind),
        "csrf_token": c.cookies["nest_csrf"],
        "back": "/somewhere",
    }


def test_stars_one_per_visitor_and_the_average_from_enough_votes(site):
    subject = "coaches.operator:flixbus"
    r = site.post("/nota/vot", data=form(site, subject, "stars", 4), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/somewhere"
    voter = site.cookies.get(service.COOKIE)
    assert voter  # set at the first vote
    site.post("/nota/vot", data=form(site, subject, "stars", 2))  # changed, not a second vote
    s = service.summary(site.db, subject)
    assert (s.count, s.total) == (1, 2)
    nest = site.app.state.nest
    assert nest.lookup("rating.summary", subject)["count"] == 1
    # two other visitors (other cookies, other browsers)
    for agent in ("browser-b", "browser-c"):
        other = TestClient(site.app)
        other.headers["user-agent"] = agent
        other.post("/nota/vot", data=form(other, subject, "stars", 5))
    s = service.summary(site.db, subject)
    assert (s.count, s.average, list(s.stars)) == (3, 4.0, [0, 1, 0, 0, 2])


def test_clearing_the_cookie_again_and_again_gives_no_more_votes(site):
    """A few people may share an address (a mobile network) with look-alike browsers: up to
    3 votes a day count apart; beyond, the same visitor clearing its cookie only changes
    its latest vote."""
    subject = "flights.airport:lrop"
    for value in (5, 5, 5, 1, 1, 1):
        site.post("/nota/vot", data=form(site, subject, "stars", value))
        site.cookies.delete(service.COOKIE)
    s = service.summary(site.db, subject)
    assert s.count == 3 and s.total == 11  # 5 + 5 + 1: the later ones changed the latest


def test_helpful_and_updown_the_same_button_takes_the_vote_back(site):
    site.post("/nota/vot", data=form(site, "content.entry:7", "helpful", 1))
    assert service.summary(site.db, "content.entry:7").up == 1
    site.post("/nota/vot", data=form(site, "content.entry:7", "helpful", 1))
    assert service.summary(site.db, "content.entry:7").count == 0  # taken back
    site.post("/nota/vot", data=form(site, "glossary.entry:3", "updown", -1))
    assert service.summary(site.db, "glossary.entry:3").score == -1


def test_only_a_subject_a_page_offered_and_values_of_its_kind(site):
    bad = form(site, "coaches.operator:flixbus", "stars", 4)
    bad["sig"] = "0" * 24
    assert site.post("/nota/vot", data=bad).status_code == 400
    assert (
        site.post("/nota/vot", data=form(site, "coaches.operator:flixbus", "stars", 9)).status_code
        == 400
    )
    assert (
        site.post(
            "/nota/vot", data=form(site, "coaches.operator:flixbus", "helpful", 3)
        ).status_code
        == 400
    )


def test_the_widget_and_its_search_engine_stars(site):
    from fastapi import Request
    from fastapi.responses import HTMLResponse

    from nest_rating.web import widget

    def page(request: Request, item: str = "Organization"):
        return HTMLResponse(
            str(widget(request, "coaches.operator:atlassib", "stars", name="Atlassib", item=item))
        )

    site.app.add_api_route("/rated", page)
    nest = site.app.state.nest
    subject = "coaches.operator:atlassib"
    html = site.get("/rated").text
    assert "Niciun vot încă" in html and "application/ld+json" not in html and 'name="sig"' in html
    for v, agent in ((5, "a"), (4, "b"), (3, "c")):
        service.vote(site.db, subject, "stars", v, f"voter-{agent}", f"print-{agent}")
    html = site.get("/rated").text
    assert "<b>4.0</b>" in html and "3 voturi" in html
    assert (
        '"ratingValue": 4.0' in html
        and '"ratingCount": 3' in html
        and '"@type": "Organization"' in html
    )
    assert "application/ld+json" not in site.get("/rated?item=").text  # not asked
    assert nest.lookup("rating.summaries", [subject])[subject]["average"] == 4.0


def test_the_admin_tools(site):
    subject = "coaches.station:arad"
    service.vote(site.db, subject, "stars", 5, "someone", "")
    for n in range(4):  # one visitor on many subjects in a day: a script, more likely
        service.vote(site.db, f"coaches.station:s{n}", "stars", 5, f"v{n}", "same-print")
    service.vote(site.db, subject, "stars", 4, "script", "same-print")
    assert [p for p, _ in service.bursts(site.db, most=3)] == ["same-print"]
    assert service.forget_print(site.db, "same-print") == 5
    assert (
        service.summary(site.db, subject).count == 1
        and service.summary(site.db, "coaches.station:s0").count == 0
    )
    service.close(site.db, subject, True)
    assert service.vote(site.db, subject, "stars", 1, "late") == "closed"
    service.reset(site.db, subject)
    assert service.summary(site.db, subject).count == 0


def test_the_voter_cookie_is_declared(site):
    page = site.get("/cookies/").text
    assert service.COOKIE in page
