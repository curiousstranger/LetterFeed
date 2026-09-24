import logging
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from app.services.feed_html import flatten_layout_tables


def _tables(html: str) -> int:
    """Count the <table> elements in `html`."""
    return len(BeautifulSoup(html, "html.parser").find_all("table"))


# Each fixture trips exactly one rule: the others would classify it as data.
@pytest.mark.parametrize(
    "html",
    [
        pytest.param(
            '<table role="presentation"><tr><th>A</th><th>B</th></tr>'
            "<tr><td>1</td><td>2</td></tr></table>",
            id="rule1-role-presentation",
        ),
        pytest.param(
            '<table role="none"><tr><th>A</th><th>B</th></tr>'
            "<tr><td>1</td><td>2</td></tr></table>",
            id="rule1-role-none",
        ),
        pytest.param(
            "<table><tr><th>A</th><th>B</th></tr>"
            '<tr><td><table role="presentation"><tr><td>x</td></tr></table></td>'
            "<td>2</td></tr></table>",
            id="rule2-contains-table",
        ),
        pytest.param(
            "<table><tr><th>A</th><th>B</th></tr></table>",
            id="rule3-single-row",
        ),
        pytest.param(
            "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>",
            id="rule4-no-row-with-two-cells",
        ),
        pytest.param(
            "<table><tr><td><p>A</p></td><td>B</td></tr>"
            "<tr><td>1</td><td>2</td></tr></table>",
            id="rule5-block-content-no-th",
        ),
    ],
)
def test_layout_table_rules_convert_to_divs(html):
    """Each layout rule, on its own, turns the table into divs."""
    out = flatten_layout_tables(html)
    assert _tables(out) == 0
    soup = BeautifulSoup(out, "html.parser")
    assert soup.find(["tr", "td", "th", "tbody"]) is None
    assert soup.find("div") is not None


def test_data_table_is_kept():
    """A header row plus rows of text is a data table and stays as is."""
    html = (
        "<table><tr><th>Ticker</th><th>Price</th></tr>"
        "<tr><td>ABC</td><td>1.00</td></tr>"
        "<tr><td>XYZ</td><td>2.50</td></tr></table>"
    )
    assert flatten_layout_tables(html) == html


def test_data_table_nested_in_layout_table_survives():
    """Converting a layout table never reaches into a nested data table."""
    data = (
        "<table><tr><th>Ticker</th><th>Price</th></tr>"
        "<tr><td>ABC</td><td>1.00</td></tr></table>"
    )
    html = (
        '<table role="presentation" width="600"><tbody><tr>'
        f'<td valign="top">{data}</td></tr></tbody></table>'
    )
    out = flatten_layout_tables(html)
    assert out == f'<div role="presentation"><div><div>{data}</div></div></div>'


def test_mailchimp_style_nesting_flattens_every_level():
    """Every level of email-style nested layout tables becomes a div."""
    html = (
        '<table align="center" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" bgcolor="#eee"><tbody><tr><td align="center" valign="top">'
        '<table role="presentation" width="600"><tbody><tr><td>'
        '<table width="100%"><tr><td><img src="https://example.test/p.jpg" '
        'width="560"></td></tr></table>'
        "</td></tr></tbody></table></td></tr></tbody></table>"
    )
    out = flatten_layout_tables(html)
    assert _tables(out) == 0
    assert '<img src="https://example.test/p.jpg" width="560"/>' in out


def test_converted_elements_lose_layout_attributes_but_keep_others():
    """Table-layout attributes go; style, class, id and the rest stay."""
    html = (
        '<table role="presentation" align="center" width="600" height="10" '
        'bgcolor="#fff" background="bg.png" cellpadding="0" cellspacing="0" '
        'border="0" style="color: red" class="wrap" id="outer">'
        '<tr valign="top" style="s1"><td colspan="2" rowspan="1" align="left" '
        'class="cell">x</td></tr></table>'
    )
    out = flatten_layout_tables(html)
    soup = BeautifulSoup(out, "html.parser")
    outer = soup.find(id="outer")
    assert outer.name == "div"
    assert outer.attrs == {
        "role": "presentation",
        "style": "color: red",
        "class": ["wrap"],
        "id": "outer",
    }
    row, cell = outer.find_all("div")
    assert row.attrs == {"style": "s1"}
    assert cell.attrs == {"class": ["cell"]}


def test_tracking_pixels_removed_and_real_images_kept():
    """Images 2px or smaller in either dimension are removed."""
    html = (
        '<p><img src="t1.gif" width="1" height="1">'
        '<img src="t2.gif" height="2">'
        '<img src="t0.gif" width="0">'
        '<img src="photo.jpg" width="600">'
        '<img src="auto.jpg" width="auto">'
        '<img src="plain.jpg"></p>'
    )
    out = flatten_layout_tables(html)
    for gone in ("t1.gif", "t2.gif", "t0.gif"):
        assert gone not in out
    for kept in ("photo.jpg", "auto.jpg", "plain.jpg"):
        assert kept in out


def test_pixel_that_html_parser_nests_an_image_under_is_still_removed(caplog):
    """A self-closing pixel after a plain <img> doesn't abort flattening.

    html.parser treats <img/> following an unclosed <img> as an open element,
    so the next image becomes its child.
    """
    html = '<img src="a.jpg"><img src="p.gif" width="1" height="1"/><img src="c.jpg">'
    with caplog.at_level(logging.WARNING, logger="app.services.feed_html"):
        out = flatten_layout_tables(html)
    assert "p.gif" not in out
    assert "a.jpg" in out and "c.jpg" in out
    assert not caplog.records


def test_real_image_nested_under_a_pixel_survives():
    """Removing a pixel keeps a real image the parser nested inside it."""
    html = (
        '<img src="a.jpg"><img src="p.gif" width="1"/>'
        '<img src="photo.jpg" width="600"><p>text</p>'
    )
    soup = BeautifulSoup(flatten_layout_tables(html), "html.parser")
    assert [i["src"] for i in soup.find_all("img")] == ["a.jpg", "photo.jpg"]
    assert "text" in soup.get_text()


def test_html_without_tables_is_unchanged():
    """HTML with no tables comes back as it went in."""
    html = '<p>Hi <b>there</b>, <a href="https://example.test/">link</a></p>'
    assert flatten_layout_tables(html) == html


@pytest.mark.parametrize("html", ["", "   \n\t "])
def test_empty_body_is_returned_unchanged(html):
    """Empty or whitespace-only input is returned untouched."""
    assert flatten_layout_tables(html) == html


def test_output_is_a_fragment():
    """No html or body wrapper is added."""
    out = flatten_layout_tables('<table role="none"><tr><td>x</td></tr></table>')
    assert "<html" not in out and "<body" not in out


def test_malformed_html_does_not_raise():
    """Unclosed tags are parsed leniently rather than raising."""
    out = flatten_layout_tables("<table><tr><td><div>unclosed<table><tr><td>x")
    assert "x" in out


def test_exception_inside_transform_returns_input_and_logs(caplog):
    """Any failure logs a warning with traceback and returns the input."""
    html = '<table role="none"><tr><td>x</td></tr></table>'
    with (
        patch("app.services.feed_html.BeautifulSoup", side_effect=RuntimeError("boom")),
        caplog.at_level(logging.WARNING, logger="app.services.feed_html"),
    ):
        assert flatten_layout_tables(html) == html
    record = next(r for r in caplog.records if r.name == "app.services.feed_html")
    assert record.levelno == logging.WARNING
    assert record.exc_info is not None
