def test_old_wordpress_links_are_sent_where_they_are_now():
    """Imported posts link to the old server (a bare IP, a folder: http://79.118.74.35/morlaca/)
    and to WordPress numbers (?p=27): a number that is an entry goes to it; a picture linked
    to its own post, or to an attachment page no longer there, opens the picture; another
    site's ?p= page is left alone."""
    from nest_content.web import _opens_with, old_links

    entries = {12: "/drumetii/per-pedes/", 27: "/obiective/vladeasa/"}
    html = (
        '<p><a href="http://79.118.74.35/morlaca/?p=27"><img src="/media/uploads/2012/12/vladeasa.JPG?w=640"></a></p>'
        '<p><a href="http://79.118.74.35/morlaca/?p=12">Per pedes</a></p>'
        '<p><a href="http://79.118.74.35/morlaca/?p=99"><img srcset="/media/uploads/a.jpg?w=320 320w"></a></p>'
        '<p><a href="http://www.muzeultaranuluiroman.ro/conferinte/?p=37"><img src="/media/uploads/b.jpg"></a></p>'
        '<p><a href="http://79.118.74.35/morlaca/despre/">Despre</a></p>'
    )
    out = old_links(html, entries.get, here="/obiective/vladeasa/")
    assert 'href="/media/uploads/2012/12/vladeasa.JPG"' in out  # its own post: the picture
    assert 'href="/drumetii/per-pedes/"' in out  # an entry: where it is now
    assert 'href="/media/uploads/a.jpg"' in out  # an attachment page gone: the picture
    assert 'href="http://www.muzeultaranuluiroman.ro/conferinte/?p=37"' in out  # another site's
    assert 'href="/despre/"' in out and "79.118.74.35" not in out  # the old server: this site
    assert _opens_with(out, "uploads/2012/12/vladeasa.JPG")
    assert not _opens_with(out, "uploads/other.jpg") and not _opens_with(out, "")
