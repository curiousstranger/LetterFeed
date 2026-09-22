import uuid
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest
from feedgen.feed import FeedGenerator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud.entries import create_entry
from app.crud.newsletters import create_newsletter
from app.schemas.entries import EntryCreate
from app.schemas.newsletters import NewsletterCreate
from app.services import feed_generator
from app.services.feed_generator import generate_feed, generate_master_feed

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


@pytest.fixture
def mock_db_session():
    """Fixture for a mock database session."""
    return MagicMock()


@patch("app.services.feed_generator.settings")
def test_generate_master_feed_respects_limit(mock_settings, mock_db_session):
    """Test that the master feed generation respects the MASTER_FEED_LIMIT."""
    # Arrange
    limit = 5
    mock_settings.master_feed_limit = limit

    # Create more mock entries than the limit
    mock_entries = [MagicMock() for _ in range(limit + 5)]

    with (
        patch(
            "app.services.feed_generator.get_all_entries", return_value=mock_entries
        ) as mock_get_all_entries,
        patch(
            "app.services.feed_generator._create_feed_generator"
        ) as mock_create_feed_generator,
        patch(
            "app.services.feed_generator._add_entries_to_feed"
        ) as mock_add_entries_to_feed,
    ):
        mock_fg = MagicMock(spec=FeedGenerator)
        mock_create_feed_generator.return_value = mock_fg
        mock_fg.atom_str.return_value = "fake_atom_string"

        # Act
        result = generate_master_feed(mock_db_session)

        # Assert
        mock_get_all_entries.assert_called_once_with(mock_db_session, limit=limit)
        mock_create_feed_generator.assert_called_once()
        mock_add_entries_to_feed.assert_called_once_with(
            mock_fg, mock_entries, is_master_feed=True
        )
        assert result == "fake_atom_string"


def _seed_newsletter_with_entries(db: Session, count: int = 2):
    """Create a newsletter with `count` entries and return (newsletter, entry ids)."""
    newsletter = create_newsletter(
        db,
        NewsletterCreate(
            name="Link Test Newsletter",
            sender_emails=[f"links_{uuid.uuid4()}@example.com"],
        ),
    )
    ids = [
        create_entry(
            db,
            EntryCreate(
                subject=f"Entry {i}",
                body=f"<p>Body {i}</p>",
                message_id=f"<links_{uuid.uuid4()}@test.com>",
            ),
            newsletter.id,
        ).id
        for i in range(count)
    ]
    return newsletter, ids


def _entry_links_by_id(feed_xml: bytes) -> dict[str, list[dict[str, str]]]:
    """Map each Atom entry's LetterFeed id to the attributes of its <link> elements."""
    root = ET.fromstring(feed_xml)
    result = {}
    for entry in root.findall("atom:entry", ATOM_NS):
        urn = entry.find("atom:id", ATOM_NS).text
        entry_id = urn.removeprefix("urn:letterfeed:entry:")
        result[entry_id] = [
            dict(link.attrib) for link in entry.findall("atom:link", ATOM_NS)
        ]
    return result


def _patched_base_url(base_url: str):
    """Patch the feed generator's settings with a different app_base_url."""
    return patch.object(
        feed_generator,
        "settings",
        settings.model_copy(update={"app_base_url": base_url}),
    )


def test_generate_feed_entries_link_to_entry_page(db_session: Session):
    """Test that each newsletter feed entry links to its /api/entries page."""
    newsletter, ids = _seed_newsletter_with_entries(db_session)

    with _patched_base_url("https://lf.example.test"):
        links = _entry_links_by_id(generate_feed(db_session, newsletter.id))

    assert sorted(links) == sorted(ids)
    for entry_id, entry_links in links.items():
        assert len(entry_links) == 1
        assert (
            entry_links[0]["href"] == f"https://lf.example.test/api/entries/{entry_id}"
        )
        assert entry_links[0].get("rel", "alternate") == "alternate"


def test_generate_master_feed_entries_link_to_entry_page(db_session: Session):
    """Test that each master feed entry links to its /api/entries page."""
    _, ids = _seed_newsletter_with_entries(db_session)

    with _patched_base_url("https://lf.example.test"):
        links = _entry_links_by_id(generate_master_feed(db_session))

    assert sorted(links) == sorted(ids)
    for entry_id, entry_links in links.items():
        assert len(entry_links) == 1
        assert (
            entry_links[0]["href"] == f"https://lf.example.test/api/entries/{entry_id}"
        )
        assert entry_links[0].get("rel", "alternate") == "alternate"


def test_entry_link_with_trailing_slash_base_url(db_session: Session):
    """Test that a trailing slash on app_base_url doesn't produce //api."""
    newsletter, ids = _seed_newsletter_with_entries(db_session, count=1)

    with _patched_base_url("https://lf.example.test/"):
        links = _entry_links_by_id(generate_feed(db_session, newsletter.id))

    assert links[ids[0]][0]["href"] == (f"https://lf.example.test/api/entries/{ids[0]}")
