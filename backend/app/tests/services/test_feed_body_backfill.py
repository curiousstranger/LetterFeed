import uuid
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.crud.entries import create_entry
from app.crud.newsletters import create_newsletter
from app.models.entries import Entry
from app.schemas.entries import EntryCreate
from app.schemas.newsletters import NewsletterCreate
from app.services.feed_body_backfill import backfill_feed_bodies
from app.services.feed_html import flatten_layout_tables

LAYOUT = '<table role="presentation"><tr><td><p>Issue {i}</p></td></tr></table>'


def _seed(db: Session, count: int, feed_body: str | None = None) -> list[str]:
    """Create `count` entries, then set each one's feed_body to `feed_body`."""
    newsletter = create_newsletter(
        db,
        NewsletterCreate(
            name="Backfill", sender_emails=[f"bf_{uuid.uuid4()}@example.com"]
        ),
    )
    ids = []
    for i in range(count):
        entry = create_entry(
            db,
            EntryCreate(
                subject=f"S{i}",
                body=LAYOUT.format(i=i),
                message_id=f"<bf_{uuid.uuid4()}@test.com>",
            ),
            newsletter.id,
        )
        entry.feed_body = feed_body
        ids.append(entry.id)
    db.commit()
    return ids


def test_backfill_fills_null_rows_across_batches(db_session: Session):
    """Null rows are filled with the transform's output, one commit per batch."""
    ids = _seed(db_session, 5)

    with patch.object(db_session, "commit", wraps=db_session.commit) as commit:
        filled = backfill_feed_bodies(db_session, batch_size=2)

    assert filled == 5
    assert commit.call_count == 3  # batches of 2, 2, 1
    db_session.expire_all()
    for entry_id in ids:
        entry = db_session.get(Entry, entry_id)
        assert entry.feed_body == flatten_layout_tables(entry.body)
        assert "<table" not in entry.feed_body


def test_backfill_leaves_filled_rows_alone(db_session: Session):
    """Rows that already have a feed_body are not touched."""
    (kept,) = _seed(db_session, 1, feed_body="<div>KEEP</div>")
    (null,) = _seed(db_session, 1)

    assert backfill_feed_bodies(db_session) == 1

    db_session.expire_all()
    assert db_session.get(Entry, kept).feed_body == "<div>KEEP</div>"
    assert db_session.get(Entry, null).feed_body is not None


def test_backfill_completes_when_transform_fails(db_session: Session):
    """A failing transform copies the body and the backfill still finishes."""
    ids = _seed(db_session, 3)

    with patch(
        "app.services.feed_html.BeautifulSoup", side_effect=RuntimeError("boom")
    ):
        filled = backfill_feed_bodies(db_session, batch_size=2)

    assert filled == 3
    db_session.expire_all()
    for entry_id in ids:
        entry = db_session.get(Entry, entry_id)
        assert entry.feed_body == entry.body


def test_backfill_with_nothing_to_do(db_session: Session):
    """With no null rows the backfill fills nothing."""
    assert backfill_feed_bodies(db_session) == 0
