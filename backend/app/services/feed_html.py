from bs4 import BeautifulSoup

from app.core.logging import get_logger

"""Rewrite newsletter HTML for feed readers that treat every table as data."""

logger = get_logger(__name__)

# A cell holding any of these is laying out content, not holding a datum.
_BLOCK_TAGS = [
    "img",
    "div",
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "blockquote",
    "table",
]

# Table-layout attributes that mean nothing on a <div>.
_LAYOUT_ATTRS = (
    "align",
    "valign",
    "width",
    "height",
    "bgcolor",
    "background",
    "cellpadding",
    "cellspacing",
    "border",
    "colspan",
    "rowspan",
)


def _own(table, names):
    """Return descendants of `table` named `names` that no nested table owns."""
    return [el for el in table.find_all(names) if el.find_parent("table") is table]


def _is_layout_table(table, rows, cells) -> bool:
    """Apply the spec's rules 1-5, in order; any match makes it a layout table."""
    if table.get("role", "").strip().lower() in ("presentation", "none"):
        return True
    if table.find("table") is not None:
        return True
    if len(rows) < 2:
        return True
    if not any(
        sum(1 for c in cells if c.find_parent("tr") is row) >= 2 for row in rows
    ):
        return True
    if not any(c.name == "th" for c in cells) and any(
        c.find(_BLOCK_TAGS) is not None for c in cells
    ):
        return True
    return False


def _is_tracking_pixel(img) -> bool:
    for attr in ("width", "height"):
        try:
            if int(str(img.get(attr, "")).strip()) <= 2:
                return True
        except ValueError:
            pass
    return False


def _flatten(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Classify every table, and collect what it owns, against the unmodified
    # tree: once an inner table is renamed to <div>, find_parent("table") would
    # attribute its rows to the outer table.
    layout = []
    for table in soup.find_all("table"):
        rows = _own(table, "tr")
        cells = _own(table, ["td", "th"])
        if _is_layout_table(table, rows, cells):
            sections = _own(table, ["tbody", "thead", "tfoot"])
            layout.append((table, sections, rows, cells))

    for table, sections, rows, cells in layout:
        for section in sections:
            section.unwrap()
        for el in (table, *rows, *cells):
            el.name = "div"
            for attr in _LAYOUT_ATTRS:
                el.attrs.pop(attr, None)

    for img in soup.find_all("img"):
        if _is_tracking_pixel(img):
            img.decompose()

    return str(soup)


def flatten_layout_tables(html: str) -> str:
    """Convert layout tables to <div>s, keep data tables, drop tracking pixels.

    Never raises: on any failure the input is returned unchanged.
    """
    if not html or not html.strip():
        return html
    try:
        return _flatten(html)
    except Exception:
        logger.warning("Could not flatten layout tables", exc_info=True)
        return html
