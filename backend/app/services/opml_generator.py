import xml.etree.ElementTree as ET

from app.core.config import settings
from app.models.newsletters import Newsletter


def _resolve_base(base_url: str | None) -> str:
    """Resolve the base URL feed links are built from, without a trailing slash."""
    return (base_url or settings.app_base_url).rstrip("/")


def opml_subscribe_url(key: str, base_url: str | None = None) -> str:
    """Build the unauthenticated subscription URL for a given key."""
    return f"{_resolve_base(base_url)}/api/feeds/opml/{key}"


def generate_opml(newsletters: list[Newsletter], base_url: str | None = None) -> bytes:
    """Build an OPML 2.0 subscription list with one outline per newsletter feed."""
    base = _resolve_base(base_url)

    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = "LetterFeed subscriptions"
    body = ET.SubElement(opml, "body")

    for newsletter in sorted(newsletters, key=lambda n: (n.name or "").casefold()):
        ET.SubElement(
            body,
            "outline",
            type="rss",
            text=newsletter.name or "",
            title=newsletter.name or "",
            xmlUrl=f"{base}/api/feeds/{newsletter.slug or newsletter.id}",
        )

    return ET.tostring(opml, encoding="utf-8", xml_declaration=True)
