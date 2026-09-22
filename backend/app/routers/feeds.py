import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.crud.newsletters import get_active_newsletters
from app.crud.settings import get_opml_key
from app.services.feed_generator import generate_feed, generate_master_feed
from app.services.opml_generator import generate_opml

logger = get_logger(__name__)
router = APIRouter()


@router.get("/feeds/all")
def get_master_feed(db: Session = Depends(get_db)):
    """Generate a master Atom feed for all newsletters."""
    logger.info("Generating master feed for all newsletters")
    feed = generate_master_feed(db)
    logger.info("Successfully generated master feed")
    return Response(content=feed, media_type="application/atom+xml")


@router.get("/feeds/opml/{key}")
def get_opml_subscription(key: str, db: Session = Depends(get_db)):
    """Serve the OPML subscription list to a reader holding the capability key.

    Unauthenticated, like every other feed route: a reader polling this URL
    cannot send a bearer token (upstream #4). The key is what stands in for
    authentication, so a mismatch is a 404 rather than a 401 -- a wrong key
    must not reveal that a right one exists. The key is never logged.
    """
    logger.info("Request for the OPML subscription list")
    expected_key = get_opml_key(db)
    if not expected_key or not secrets.compare_digest(key, expected_key):
        logger.warning("Rejected an OPML subscription request with an invalid key")
        raise HTTPException(status_code=404, detail="Not found")

    opml = generate_opml(get_active_newsletters(db))
    return Response(content=opml, media_type="text/x-opml")


@router.get("/feeds/{feed_identifier}")
def get_newsletter_feed(feed_identifier: str, db: Session = Depends(get_db)):
    """Generate an Atom feed for a specific newsletter."""
    logger.info(f"Generating feed for newsletter with identifier={feed_identifier}")
    feed = generate_feed(db, feed_identifier)
    if not feed:
        logger.warning(
            f"Newsletter with identifier={feed_identifier} not found, cannot generate feed."
        )
        raise HTTPException(status_code=404, detail="Newsletter not found")

    logger.info(
        f"Successfully generated feed for newsletter with identifier={feed_identifier}"
    )
    return Response(content=feed, media_type="application/atom+xml")
