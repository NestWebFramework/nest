import pytest

from nest.security import DEFAULT_CSP, CspError, build_csp


def directive(policy, name):
    for part in policy.split(";"):
        words = part.split()
        if words and words[0] == name:
            return words[1:]
    return None


def test_without_sections_the_policy_is_the_default():
    assert build_csp([]) == DEFAULT_CSP


def test_packages_add_sources_to_the_directives_they_may_extend():
    policy = build_csp(
        [
            ("maps", {"img-src": ["https://tile.openstreetmap.org"]}),
            ("content", {"frame-src": "https://www.youtube-nocookie.com"}),
            ("app", {"img-src": ["https://tile.openstreetmap.org", "https://*.example.ro/x/"]}),
        ]
    )
    assert directive(policy, "img-src") == [
        "'self'",
        "data:",
        "https://tile.openstreetmap.org",
        "https://*.example.ro/x/",
    ]
    assert directive(policy, "frame-src") == ["'self'", "https://www.youtube-nocookie.com"]
    assert directive(policy, "script-src") == ["'self'"]


def test_scripts_wildcards_keywords_and_http_are_refused():
    with pytest.raises(CspError) as e:
        build_csp(
            [
                ("bad", {"script-src": ["https://cdn.example.com"]}),
                ("worse", {"img-src": ["*", "'unsafe-inline'", "http://plain.example.com"]}),
                ("odd", ["https://x.example.com"]),
            ]
        )
    text = str(e.value)
    assert "bad: csp may extend" in text and "not 'script-src'" in text
    assert "'*' is not an https source" in text
    assert "''unsafe-inline'' is not" in text
    assert "'http://plain.example.com' is not" in text
    assert "odd: csp is a mapping" in text
