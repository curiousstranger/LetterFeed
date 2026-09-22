from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.crud.entries import get_entry

logger = get_logger(__name__)
router = APIRouter()

# The entry body is untrusted, sender-controlled HTML served on the same
# origin as the UI and API. The CSP sandbox omits allow-same-origin, so the
# page gets an opaque origin and can't read the UI's localStorage token or make
# credentialed requests. Page script is blocked by default-src 'none' (no
# script-src), which covers inline, external, event-handler and javascript:
# URLs. allow-scripts is there only so reader apps (e.g. Current, on WebKit)
# can run their own extraction JS in the page; WebKit refuses all host-app JS
# in a sandbox without it. Never add allow-same-origin. Forms, framing and
# <base> are blocked; images, styles, fonts and media may load so newsletter
# layouts still render.
#
# INVARIANT: LetterFeed must never add a state-changing GET route. The sandbox
# does not stop same-origin subresource requests: <img src="/api/..."> in an
# entry still sends a GET.
SAFETY_HEADERS = {
    "Content-Security-Policy": (
        "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; "
        "default-src 'none'; img-src * data:; style-src * 'unsafe-inline'; "
        "font-src * data:; media-src *; form-action 'none'; base-uri 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@router.get("/entries/{entry_id}")
def get_entry_page(entry_id: str, db: Session = Depends(get_db)):
    """Serve an entry's stored body as a sandboxed standalone HTML page."""
    logger.info(f"Serving entry page for entry_id={entry_id}")
    entry = get_entry(db, entry_id)
    if not entry:
        logger.warning(f"Entry with id={entry_id} not found")
        raise HTTPException(status_code=404, detail="Entry not found")
    return Response(
        content=entry.body,
        media_type="text/html; charset=utf-8",
        headers=SAFETY_HEADERS,
    )
