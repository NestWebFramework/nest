"""The docs module: Markdown rendered safely, a tree of pages with a menu, links made the
site's, pictures served, search, reference pages from the manifests, the landing page,
and the links that lead nowhere found."""

import textwrap

import pytest
from fastapi.testclient import TestClient
from nest_docs.markdown import render

from nest import create_app

APP = """
module: {name: manual, id: test.app.manual, type: application, version: 0.1.0}
application: {title: Manual, port: 8000, theme: base, languages: [en]}
modules:
  - {name: docs, route: /docs, config: {tree: book, home: true}}
bind:
  nest.db: {providers: [db-sqlite]}
  nest.search: {providers: [search-sqlite]}
"""


def test_markdown_is_rendered_and_nothing_raw_gets_through():
    page = render(
        textwrap.dedent(
            """\
            ---
            title: "A page"
            description: "What it says"
            ---
            # Heading one
            Some *text*, **strong**, `code` and a [link](other.md).

            ## Twice
            ## Twice

            - a
              - nested
            - b

            ```python
            print("x")
            ```

            > [!WARNING]
            > Careful.

            | k | v |
            |---|--:|
            | a | 1 |

            <script>alert(1)</script> [bad](javascript:alert(1))
            """
        )
    )
    html = str(page.html)
    assert page.title == "A page" and page.meta["description"] == "What it says"
    assert [h.anchor for h in page.headings] == ["heading-one", "twice", "twice-1"]
    assert (
        "<em>text</em>" in html
        and "<strong>strong</strong>" in html
        and "<code>code</code>" in html
    )
    assert "<ul><li>a<ul><li>nested</li></ul></li><li>b</li></ul>" in html
    assert 'class="callout callout-warning"' in html and 'class="align-right"' in html
    assert '<span class="nb">print</span>' in html  # highlighted
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "javascript:" not in html


@pytest.fixture
def manual(tmp_path):
    root = tmp_path / "manual"
    book = root / "book"
    (book / "start").mkdir(parents=True)
    (book / "images").mkdir()
    (root / "module.yml").write_text(textwrap.dedent(APP), encoding="utf-8")
    (book / "site.yml").write_text(
        "title: The manual\nsections:\n  - title: Start\n    pages: [start/install, start/use]\n"
        "  - title: Modules\n    reference: modules\n",
        encoding="utf-8",
    )
    (book / "index.md").write_text(
        "# The manual\n\nStart with [installing](start/install.md).\n", encoding="utf-8"
    )
    (book / "landing.md").write_text(
        '---\ntitle: "Hello"\nhero: {title: "Make things", lead: "Quickly.", actions: [{label: Go, href: /docs/}]}\n'
        "features: [{title: Fast, text: Very.}]\n---\nMore below.\n",
        encoding="utf-8",
    )
    (book / "start" / "install.md").write_text(
        "# Install\n\n![A shot](../images/shot.png)\n\nThen [use it](use.md#run) or [nowhere](missing.md). Run backups often.\n",
        encoding="utf-8",
    )
    (book / "start" / "use.md").write_text(
        "# Use\n\n## Run\n\nGo.\n\n## Stop\n\nStop.\n", encoding="utf-8"
    )
    (book / "images" / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    app = create_app(root, environ={"NEST_APP_WORKSPACE": str(tmp_path / "ws")})
    with TestClient(app) as c:
        c.tree = app.state.nest.module_state["docs"]["tree"]
        yield c


def test_pages_menu_links_and_pictures(manual):
    page = manual.get("/docs/start/install").text
    assert 'href="/docs/start/use#run"' in page  # a page's link made the site's
    assert 'src="/docs/_files/images/shot.png"' in page
    assert 'aria-current="page"' in page and ">Use</a>" in page  # the menu, this page marked
    assert manual.get("/docs/_files/images/shot.png").status_code == 200
    assert manual.get("/docs/_files/../module.yml").status_code == 404  # nothing outside the tree
    assert manual.get("/docs/nope").status_code == 404
    use = manual.get("/docs/start/use").text
    assert 'href="#run"' in use and 'href="#stop"' in use  # the contents beside it
    assert "← " in use  # the page before


def test_the_reference_comes_from_the_manifests(manual):
    entries = [e.key for s in manual.tree.sections for e in s.entries]
    assert "reference/modules/docs" in entries
    page = manual.get("/docs/reference/modules/docs").text
    assert (
        "Documentation" in page and "<code>edit_url</code>" in page
    )  # its settings, from module.yml


def test_search_and_landing(manual):
    hits = manual.get("/docs/search?q=backups").text
    assert "/docs/start/install" in hits
    home = manual.get("/").text
    assert "Make things" in home and "Quickly." in home and "Fast" in home and "More below." in home


def test_broken_links_are_found(manual):
    problems = manual.tree.broken()
    assert problems == ["start/install: no page /docs/start/missing"]
