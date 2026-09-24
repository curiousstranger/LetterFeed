from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.entries import Entry
from app.services.feed_html import flatten_layout_tables

"""One-off fill of entries.feed_body for entries created before it existed."""

logger = get_logger(__name__)


def backfill_feed_bodies(db: Session, batch_size: int = 50) -> int:
    """Fill every null feed_body, committing per batch; return how many."""
    todo = db.query(Entry).filter(Entry.feed_body.is_(None)).count()
    logger.info(f"Feed body backfill starting: {todo} entries to fill")

    filled = 0
    last_id = ""
    while True:
        # Commit per batch so the SQLite write lock is held only briefly while
        # the email job may be running in parallel.
        batch = (
            db.query(Entry)
            .filter(Entry.feed_body.is_(None), Entry.id > last_id)
            .order_by(Entry.id)
            .limit(batch_size)
            .all()
        )
        if not batch:
            break
        for entry in batch:
            entry.feed_body = flatten_layout_tables(entry.body or "")
        last_id = batch[-1].id
        db.commit()
        filled += len(batch)

    logger.info(f"Feed body backfill finished: filled {filled} entries")
    return filled
