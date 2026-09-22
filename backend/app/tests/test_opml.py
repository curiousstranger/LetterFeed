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


# --- Keyed subscription URL (dynamic OPML for readers that cannot send a token) ---


def _key(db: Session) -> str:
    from app.crud.settings import get_or_create_opml_key

    return get_or_create_opml_key(db)


def test_opml_key_is_generated_once_and_stable(db_session: Session):
    """The key is generated on first use and does not change afterwards."""
    first = _key(db_session)
    assert first
    assert _key(db_session) == first


def test_opml_key_has_enough_entropy(db_session: Session):
    """The key is long enough to be unguessable, not a short token."""
    assert len(_key(db_session)) >= 32


def test_subscribe_url_returns_the_keyed_url(client: TestClient, db_session: Session):
    """The protected endpoint hands the UI the full subscription URL."""
    response = client.get("/newsletters/opml/subscribe-url")
    assert response.status_code == 200
    base = settings.app_base_url.rstrip("/")
    assert response.json()["url"] == f"{base}/api/feeds/opml/{_key(db_session)}"


def test_keyed_opml_serves_the_same_outlines_as_the_download(
    client: TestClient, db_session: Session
):
    """The keyed URL and the download return the same subscription list."""
    _add_newsletter(db_session, "Alpha", "a@x.com")
    inactive = _add_newsletter(db_session, "Inactive", "i@x.com")
    inactive.is_active = False
    db_session.commit()

    keyed = client.get(f"/feeds/opml/{_key(db_session)}")
    assert keyed.status_code == 200
    assert [o.get("text") for o in _outlines(keyed)] == ["Alpha"]
    assert keyed.content == client.get("/newsletters/opml").content


def test_keyed_opml_is_not_served_as_an_attachment(
    client: TestClient, db_session: Session
):
    """A polled resource is inline; only the download is an attachment."""
    response = client.get(f"/feeds/opml/{_key(db_session)}")
    assert response.headers["content-type"].startswith("text/x-opml")
    assert "content-disposition" not in response.headers


def test_keyed_opml_rejects_a_wrong_key_with_404(
    client: TestClient, db_session: Session
):
    """A wrong key is indistinguishable from a path that does not exist."""
    _key(db_session)
    assert client.get("/feeds/opml/not-the-key").status_code == 404


def test_keyed_opml_404s_before_a_key_exists(client: TestClient, db_session: Session):
    """An install upgraded into this feature has no key until an admin asks.

    The unauthenticated route must not fill one in, or hitting the URL would
    bring the very thing it is asking for into existence.
    """
    from app.models.settings import Settings as SettingsModel

    db_settings = db_session.query(SettingsModel).first()
    db_settings.opml_key = None
    db_session.commit()

    assert client.get("/feeds/opml/anything").status_code == 404
    db_session.refresh(db_settings)
    assert db_settings.opml_key is None


def test_keyed_opml_is_public_when_auth_is_enabled(
    client: TestClient, db_session: Session
):
    """The keyed URL works without a token: readers cannot send one."""
    _enable_auth(db_session)
    _add_newsletter(db_session, "Alpha", "a@x.com")

    response = client.get(f"/feeds/opml/{_key(db_session)}")
    assert response.status_code == 200
    assert [o.get("text") for o in _outlines(response)] == ["Alpha"]


def test_keyed_opml_rejects_a_wrong_key_even_with_a_valid_token(
    client: TestClient, db_session: Session
):
    """A login token is not a substitute for the key."""
    _enable_auth(db_session)
    _key(db_session)
    token = client.post(
        "/auth/login", data={"username": "admin", "password": "password"}
    ).json()["access_token"]

    response = client.get(
        "/feeds/opml/not-the-key", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def test_keyed_opml_never_logs_the_key(client: TestClient, db_session: Session, caplog):
    """The application's own logs must not repeat the key back.

    Scoped to the app's loggers on purpose. A URL-borne key unavoidably reaches
    an access log (uvicorn's, and any reverse proxy's) -- that is inherent to
    every capability URL. What is in our hands is not writing it a second time
    into the application log, where it would outlive log rotation policies
    aimed at access logs.
    """
    import logging

    key = _key(db_session)
    with caplog.at_level(logging.DEBUG):
        assert client.get(f"/feeds/opml/{key}").status_code == 200

    app_logs = [r.getMessage() for r in caplog.records if r.name.startswith("app.")]
    assert app_logs, "expected the request to log something, or this proves nothing"
    assert not any(key in message for message in app_logs)


def test_subscribe_url_requires_a_token_when_auth_is_enabled(
    client: TestClient, db_session: Session
):
    """The key is not discoverable without logging in."""
    _enable_auth(db_session)
    assert client.get("/newsletters/opml/subscribe-url").status_code == 401


def test_rotate_requires_a_token_when_auth_is_enabled(
    client: TestClient, db_session: Session
):
    """Only an authenticated admin can rotate the key."""
    _enable_auth(db_session)
    assert client.post("/newsletters/opml/subscribe-url/rotate").status_code == 401


def test_rotating_the_key_invalidates_the_old_url(
    client: TestClient, db_session: Session
):
    """Rotation is the revocation path for a leaked URL."""
    old_key = _key(db_session)

    response = client.post("/newsletters/opml/subscribe-url/rotate")
    assert response.status_code == 200
    new_url = response.json()["url"]
    assert old_key not in new_url

    assert client.get(f"/feeds/opml/{old_key}").status_code == 404
    assert client.get(f"/feeds/opml/{new_url.rsplit('/', 1)[1]}").status_code == 200


def test_opml_key_is_absent_from_the_settings_response(
    client: TestClient, db_session: Session
):
    """The key is surfaced by one endpoint only, not wherever settings are read."""
    key = _key(db_session)
    response = client.get("/imap/settings")
    assert response.status_code == 200
    assert key not in response.text


def test_settings_update_cannot_set_the_opml_key(
    client: TestClient, db_session: Session
):
    """A client must not be able to choose the key by posting settings.

    Regression guard: SettingsCreate has no opml_key field, so pydantic drops
    it. If someone later widens that schema, an attacker who can reach the
    settings endpoint could pin the key to a value they already know.
    """
    key = _key(db_session)

    response = client.post(
        "/imap/settings",
        json={
            "imap_server": "test.com",
            "imap_username": "test",
            "search_folder": "INBOX",
            "mark_as_read": False,
            "email_check_interval": 15,
            "auto_add_new_senders": False,
            "opml_key": "chosen-by-the-caller",
        },
    )
    assert response.status_code == 200
    assert _key(db_session) == key
