import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud.newsletters import create_newsletter
from app.crud.settings import create_or_update_settings
from app.schemas.newsletters import NewsletterCreate
from app.schemas.settings import SettingsCreate


def _add_newsletter(db: Session, name: str, email: str, slug: str | None = None):
    return create_newsletter(
        db, NewsletterCreate(name=name, slug=slug, sender_emails=[email])
    )


def _outlines(response):
    root = ET.fromstring(response.content)
    return root.findall("./body/outline")


def test_opml_headers(client: TestClient, db_session: Session):
    """The export is served as an OPML attachment."""
    response = client.get("/newsletters/opml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-opml")
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="letterfeed.opml"'
    )


def test_opml_empty_is_valid(client: TestClient, db_session: Session):
    """With no newsletters the export is a valid, empty OPML 2.0 document."""
    response = client.get("/newsletters/opml")
    root = ET.fromstring(response.content)
    assert root.tag == "opml"
    assert root.get("version") == "2.0"
    assert root.find("./head/title") is not None
    assert root.find("./body") is not None
    assert _outlines(response) == []


def test_opml_only_active_newsletters(client: TestClient, db_session: Session):
    """Inactive newsletters are left out of the export."""
    _add_newsletter(db_session, "Active", "active@example.com")
    inactive = _add_newsletter(db_session, "Inactive", "inactive@example.com")
    inactive.is_active = False
    db_session.commit()

    names = [o.get("text") for o in _outlines(client.get("/newsletters/opml"))]
    assert names == ["Active"]


def test_opml_sorted_by_name(client: TestClient, db_session: Session):
    """Outlines are sorted by newsletter name."""
    for name, email in [
        ("Charlie", "c@x.com"),
        ("alpha", "a@x.com"),
        ("Bravo", "b@x.com"),
    ]:
        _add_newsletter(db_session, name, email)

    names = [o.get("text") for o in _outlines(client.get("/newsletters/opml"))]
    assert names == ["alpha", "Bravo", "Charlie"]


def test_opml_outline_attributes_prefer_slug(client: TestClient, db_session: Session):
    """Each outline is an rss entry whose URL uses the slug when there is one."""
    with_slug = _add_newsletter(db_session, "Sluggy", "s@x.com", slug="sluggy")
    without_slug = _add_newsletter(db_session, "Plain", "p@x.com")

    outlines = {o.get("text"): o for o in _outlines(client.get("/newsletters/opml"))}
    base = settings.app_base_url.rstrip("/")
    assert outlines["Sluggy"].get("type") == "rss"
    assert outlines["Sluggy"].get("title") == "Sluggy"
    assert outlines["Sluggy"].get("xmlUrl") == f"{base}/api/feeds/sluggy"
    assert with_slug.id not in outlines["Sluggy"].get("xmlUrl")
    assert outlines["Plain"].get("xmlUrl") == f"{base}/api/feeds/{without_slug.id}"


def test_opml_base_url_override(client: TestClient, db_session: Session):
    """A base_url query param overrides the configured base, minus trailing slash."""
    _add_newsletter(db_session, "Sluggy", "s@x.com", slug="sluggy")

    response = client.get(
        "/newsletters/opml", params={"base_url": "https://feeds.example.com/"}
    )
    (outline,) = _outlines(response)
    assert outline.get("xmlUrl") == "https://feeds.example.com/api/feeds/sluggy"


def test_opml_escapes_special_characters(client: TestClient, db_session: Session):
    """Names with XML-special characters round-trip intact."""
    name = 'Tom & Jerry\'s <"Weekly">'
    _add_newsletter(db_session, name, "tj@x.com")

    (outline,) = _outlines(client.get("/newsletters/opml"))
    assert outline.get("text") == name
    assert outline.get("title") == name


def test_opml_includes_more_than_100_newsletters(
    client: TestClient, db_session: Session
):
    """Every active newsletter is exported, with no pagination cap."""
    for i in range(150):
        _add_newsletter(db_session, f"Newsletter {i:03d}", f"n{i}@x.com")

    assert len(_outlines(client.get("/newsletters/opml"))) == 150


def _enable_auth(db: Session):
    create_or_update_settings(
        db,
        SettingsCreate(
            imap_server="test.com",
            imap_username="test",
            imap_password="password",
            auth_username="admin",
            auth_password="password",
        ),
    )


def test_opml_requires_token_when_auth_enabled(client: TestClient, db_session: Session):
    """The export is protected like the rest of the newsletters API."""
    _enable_auth(db_session)
    response = client.get("/newsletters/opml")
    assert response.status_code == 401


def test_opml_with_valid_token(client: TestClient, db_session: Session):
    """A bearer token from /auth/login grants access to the export."""
    _enable_auth(db_session)
    _add_newsletter(db_session, "Sluggy", "s@x.com", slug="sluggy")
    token = client.post(
        "/auth/login", data={"username": "admin", "password": "password"}
    ).json()["access_token"]

    response = client.get(
        "/newsletters/opml", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert [o.get("text") for o in _outlines(response)] == ["Sluggy"]
