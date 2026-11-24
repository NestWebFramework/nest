"""Pictures in an article shown as the gallery shows its photos: an emphasized one framed,
captioned, opening large; emphasized ones side by side a mini-gallery; with the site's
setting every picture opens large; a picture linking to another page keeps its link."""

from nest_gallery.spotlight import transform

VIEWER = "/assets/gallery/lightbox.js?v=1"


def pic(name, cls="", alt=""):
    c = f' class="{cls}"' if cls else ""
    return f'<img src="/media/uploads/{name}?w=640" srcset="/media/uploads/{name}?w=320 320w"{c} alt="{alt}">'


def test_an_emphasized_picture_is_framed_and_opens_large():
    out = transform(
        "<p>Text</p>" + pic("varf.jpg", "evidentiat aligncenter", "Vârful Vlădeasa"), viewer=VIEWER
    )
    html = out["html"]
    assert out["used"] and f'<script src="{VIEWER}" defer></script>' in html
    assert (
        '<figure class="nest-spot">' in html and "<figcaption>Vârful Vlădeasa</figcaption>" in html
    )
    assert (
        'href="/media/uploads/varf.jpg?w=1920" class="nest-spot-link" data-lightbox="article"'
        in html
    )


def test_emphasized_pictures_side_by_side_are_a_mini_gallery():
    body = (
        "<p>"
        + pic("a.jpg", "evidentiat")
        + "</p><p>"
        + pic("b.jpg", "evidentiat")
        + "</p>"
        + pic("c.jpg", "evidentiat")
    )
    body += "<p>Some words between.</p>" + pic("d.jpg", "evidentiat")
    html = transform(body)["html"]
    assert html.count('<div class="nest-spot-grid">') == 1
    grid = html[html.index('<div class="nest-spot-grid">') :]
    assert (
        grid.index("a.jpg") < grid.index("c.jpg") < grid.index("</div>") < grid.index("d.jpg")
    )  # d stands alone


def test_every_picture_opens_large_with_the_setting_and_page_links_stay():
    body = (
        pic("plain.jpg", alt="Satul") + '<a href="/obiective/bologa/">' + pic("bologa.jpg") + "</a>"
    )
    body += '<img src="https://example.org/x.jpg">'
    off = transform(body)
    assert not off["used"] and off["html"] == body  # nothing asked: as it was
    on = transform(body, everything=True, viewer=VIEWER)["html"]
    assert (
        '<a href="/media/uploads/plain.jpg?w=1920" class="nest-zoom" data-lightbox="article" data-caption="Satul">'
        in on
    )
    assert '<a href="/obiective/bologa/">' in on and "bologa.jpg?w=1920" not in on  # its link kept
    assert 'href="https://example.org' not in on  # another site's picture: left alone


def test_a_picture_already_linked_to_its_file_opens_in_the_viewer():
    body = '<a href="/media/uploads/z.jpg">' + pic("z.jpg", "evidentiat") + "</a>"
    html = transform(body)["html"]
    assert html.count("<a ") == 1 and 'data-lightbox="article"' in html
