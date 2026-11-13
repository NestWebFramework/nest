"""search-sqlite on its own: folding, prefixes, scope, ranking, and no query syntax."""

from types import SimpleNamespace

import pytest
from nest_search import Document, Search, highlight
from nest_search_sqlite import create, match_expression

from nest.bind import conformance


@pytest.fixture
def index():
    s = create(SimpleNamespace(path=":memory:", title_weight=10.0), None)
    s.index(
        [
            Document("t", "1", "știință", "cunoaștere sistematică", "/a", "moldova"),
            Document("t", "2", "jinars", "țuică, vinars, băutură din prune", "/b", "ardeal"),
            Document("t", "3", "ciorbă", "supă acră; nu e știință", "/c", "moldova"),
            Document("p", "1", "știință", "an article", "/p", ""),
        ]
    )
    yield s
    s.close()


def test_it_keeps_the_interface(index):
    assert conformance(Search, index, "search-sqlite") == []


def test_diacritics_fold_both_ways_and_titles_rank_first(index):
    assert [h.id for h in index.query("STIINTA", kind="t")] == ["1", "3"]
    assert [h.title for h in index.query("tuica")] == ["jinars"]
    assert [h.title for h in index.query("ştiinţă", kind="t")] == [
        "știință",
        "ciorbă",
    ]  # cedilla forms


def test_the_last_word_is_a_prefix_and_every_word_must_match(index):
    assert [h.title for h in index.query("vin")] == ["jinars"]
    assert index.query("supa stiin")[0].title == "ciorbă"
    assert index.query("supa jinars") == []


def test_scope_kind_count_and_suggest(index):
    assert [h.id for h in index.query("stiinta", scope="ardeal")] == []
    assert index.count("stiinta") == 3 and index.count("stiinta", kind="t") == 2
    assert [h.title for h in index.suggest("ci")] == ["ciorbă"]


def test_nothing_typed_is_query_syntax(index):
    for text in ['x" OR 1=1 --', "title:jinars", "NEAR(a b)", "*", "", "   ", '"""']:
        index.query(text)  # never raises
    assert match_expression('a" OR "b') == '"a" AND "OR" AND "b"*'
    assert match_expression("!!!") is None


def test_snippets_are_escaped_then_marked(index):
    index.index([Document("t", "9", "x", "<b>vinars</b> & co", "/x")])
    hit = index.query("vinars", kind="t")[0]
    html = str(hit.snippet_html())
    assert "&lt;" in html and "<mark>" in html and "<b>" not in html
    assert str(highlight("a\x02b\x03")) == "a<mark>b</mark>"


def test_reindexing_replaces_and_removing_forgets(index):
    index.index([Document("t", "2", "jinars", "rachiu", "/b", "ardeal")])
    assert index.query("tuica") == [] and index.count("rachiu") == 1
    index.remove("t", ["2"])
    assert index.count("rachiu") == 0
    index.clear("t")
    assert index.count("stiinta") == 1
