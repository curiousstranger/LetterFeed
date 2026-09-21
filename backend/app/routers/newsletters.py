from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.crud.entries import create_entry
from app.crud.newsletters import (
    create_newsletter,
    delete_newsletter,
    get_newsletter_by_identifier,
    get_newsletters,
    update_newsletter,
)
from app.schemas.entries import Entry, EntryCreate
from app.schemas.newsletters import Newsletter, NewsletterCreate, NewsletterUpdate

logger = get_logger(__name__)
router = APIRouter()


@router.post("/newsletters", response_model=Newsletter)
def create_new_newsletter(newsletter: NewsletterCreate, db: Session = Depends(get_db)):
    """Create a new newsletter."""
    logger.info(
        f"Request to create new newsletter for senders {newsletter.sender_emails}"
    )
    db_newsletter = create_newsletter(db=db, newsletter=newsletter)
    if db_newsletter is None:
        raise HTTPException(status_code=409, detail="Slug already in use")
    return db_newsletter


@router.get("/newsletters", response_model=List[Newsletter])
def read_newsletters(
    skip: int = 0, limit: int | None = None, db: Session = Depends(get_db)
):
    """Retrieve a list of newsletters."""
    logger.info(f"Request to read newsletters with skip={skip}, limit={limit}")
    newsletters = get_newsletters(db, skip=skip, limit=limit)
    return newsletters


@router.get("/newsletters/{newsletter_id}", response_model=Newsletter)
def read_newsletter(newsletter_id: str, db: Session = Depends(get_db)):
    """Retrieve a single newsletter by its ID."""
    logger.info(f"Request to read newsletter with id={newsletter_id}")
    db_newsletter = get_newsletter_by_identifier(db, identifier=newsletter_id)
    if db_newsletter is None:
        logger.warning(f"Newsletter with id={newsletter_id} not found")
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return db_newsletter


@router.put("/newsletters/{newsletter_id}", response_model=Newsletter)
def update_existing_newsletter(
    newsletter_id: str, newsletter: NewsletterUpdate, db: Session = Depends(get_db)
):
    """Update an existing newsletter."""
    logger.info(f"Request to update newsletter with id={newsletter_id}")
    db_newsletter = update_newsletter(
        db, newsletter_id=newsletter_id, newsletter_update=newsletter
    )
    if db_newsletter is None:
        logger.warning(f"Newsletter with id={newsletter_id} not found, cannot update")
        raise HTTPException(status_code=404, detail="Newsletter not found")
    if db_newsletter == "conflict":
        raise HTTPException(status_code=409, detail="Slug already in use")
    return db_newsletter


@router.delete("/newsletters/{newsletter_id}", response_model=Newsletter)
def delete_existing_newsletter(newsletter_id: str, db: Session = Depends(get_db)):
    """Delete a newsletter by its ID."""
    logger.info(f"Request to delete newsletter with id={newsletter_id}")
    db_newsletter = delete_newsletter(db, newsletter_id=newsletter_id)
    if db_newsletter is None:
        logger.warning(f"Newsletter with id={newsletter_id} not found, cannot delete")
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return db_newsletter


@router.post("/newsletters/{newsletter_id}/entries", response_model=Entry)
def create_newsletter_entry(
    newsletter_id: str, entry: EntryCreate, db: Session = Depends(get_db)
):
    """Create a new entry for a specific newsletter."""
    logger.info(f"Request to create entry for newsletter_id={newsletter_id}")
    db_newsletter = get_newsletter_by_identifier(db, identifier=newsletter_id)
    if db_newsletter is None:
        logger.warning(
            f"Newsletter with id={newsletter_id} not found, cannot create entry"
        )
        raise HTTPException(status_code=404, detail="Newsletter not found")
    return create_entry(db=db, entry=entry, newsletter_id=newsletter_id)
