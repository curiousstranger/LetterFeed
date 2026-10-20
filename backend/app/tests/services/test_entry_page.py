import pytest

from app.services.entry_page import strip_penalized_heading_classes


def test_strips_penalized_class_from_heading():
    """Substack's heading class contains "header", which Readability discards."""
    html = '<h2 class="header-anchor-post" style="color: red"><a href="x">t</a></h2>'

    assert (
        strip_penalized_heading_classes(html)
        == '<h2 style="color: red"><a href="x">t</a></h2>'
    )


def test_keeps_unpenalized_tokens_in_heading_class():
    """Only the penalized tokens go; the heading keeps its other classes."""
    html = '<h3 class="title header-anchor-post subtitle">t</h3>'

    assert strip_penalized_heading_classes(html) == '<h3 class="title subtitle">t</h3>'


def test_leaves_heading_with_only_unpenalized_classes_unchanged():
    """A heading with no penalized token is left exactly as it was."""
    html = '<h1 class="post-title published">t</h1>'

    assert strip_penalized_heading_classes(html) == html


@pytest.mark.parametrize(
    "html",
    [
        '<div class="header">t</div>',
        '<header class="footer">t</header>',
        '<hr class="sponsor">',
        '<p class="share">t</p>',
    ],
)
def test_leaves_non_heading_elements_unchanged(html):
    """Only h1-h6 change, so real mastheads and footers still get dropped."""
    assert strip_penalized_heading_classes(html) == html


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<h2 class='sponsor-head'>t</h2>", "<h2>t</h2>"),
        ("<h2 class=footer-title>t</h2>", "<h2>t</h2>"),
        ('<H4 CLASS="Header">t</H4>', "<H4>t</H4>"),
        ('<h5\nclass = "share x">t</h5>', '<h5\nclass = "x">t</h5>'),
    ],
)
def test_handles_quoting_case_and_whitespace(html, expected):
    """Single, bare and spaced attribute syntax and uppercase names all match."""
    assert strip_penalized_heading_classes(html) == expected


def test_ignores_class_lookalikes_inside_other_attributes():
    """A ">" or "class=" inside another attribute isn't taken for a class."""
    html = '<h2 title="a > class=header" data-class="header">t</h2>'

    assert strip_penalized_heading_classes(html) == html


def test_leaves_rest_of_document_byte_identical():
    """No parser round-trip: whitespace, entities and odd markup survive as-is."""
    html = (
        "<!DOCTYPE html>\n<html><body>&nbsp;<img src=a><img/>\n"
        '<table><tr><td><h2 class="header-anchor-post">t</h2></td></tr></table>'
        "<p>unclosed</body></html>"
    )
    expected = html.replace(' class="header-anchor-post"', "")

    assert strip_penalized_heading_classes(html) == expected
