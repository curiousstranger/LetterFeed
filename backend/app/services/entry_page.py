import re

"""Keep reader apps' article extractors from discarding an entry's headings."""

# Mozilla Readability 0.6.0's unlikelyCandidates and negative patterns, which
# reader apps (Current, Safari Reader) run on the entry page. An element whose
# class matches is dropped or scored down, so Substack's
# <h2 class="header-anchor-post"> loses every section heading to "header".
_PENALIZED = re.compile(
    r"-ad-|ai2html|banner|breadcrumbs|combx|comment|community|cover-wrap|"
    r"disqus|extra|footer|gdpr|header|legends|menu|related|remark|replies|rss|"
    r"shoutbox|sidebar|skyscraper|social|sponsor|supplemental|ad-break|agegate|"
    r"pagination|pager|popup|yom-remote|hidden|^hid$|com-|contact|masthead|"
    r"media|meta|outbrain|promo|scroll|share|shopping|tags|widget",
    re.IGNORECASE,
)

_ATTR = r"""[^\s"'>/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?"""

# A heading start tag. Attributes are matched whole so that a ">" or a
# "class=" inside a quoted value can't end the tag or pass for the attribute.
_HEADING_TAG = re.compile(rf"<h[1-6](?:\s+{_ATTR})*\s*/?>", re.IGNORECASE)

_CLASS_ATTR = re.compile(
    r"""(\s+class\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.IGNORECASE
)
_ANY_ATTR = re.compile(rf"\s+{_ATTR}")


def _clean_class(attr: re.Match) -> str:
    m = _CLASS_ATTR.fullmatch(attr.group(0))
    if not m:
        return attr.group(0)
    prefix, double, single, bare = m.groups()
    if double is not None:
        value, quote = double, '"'
    elif single is not None:
        value, quote = single, "'"
    else:
        value, quote = bare, '"'
    tokens = value.split()
    kept = [c for c in tokens if not _PENALIZED.search(c)]
    if len(kept) == len(tokens):
        return attr.group(0)
    if not kept:
        return ""
    return f"{prefix}{quote}{' '.join(kept)}{quote}"


def _clean_heading(tag: re.Match) -> str:
    return _ANY_ATTR.sub(_clean_class, tag.group(0))


def strip_penalized_heading_classes(html: str) -> str:
    """Drop the class tokens Readability penalizes from h1-h6 start tags.

    Only those tokens change; everything else is returned byte for byte, since a
    parser round-trip alters some newsletters enough to change extraction.
    """
    return _HEADING_TAG.sub(_clean_heading, html)
