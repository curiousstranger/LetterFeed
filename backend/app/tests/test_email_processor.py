import imaplib
from email.message import Message
from unittest.mock import MagicMock, patch

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import engine
from app.crud.newsletters import create_newsletter
from app.crud.settings import create_or_update_settings
from app.models.entries import Entry
from app.models.newsletters import Newsletter, Sender
from app.schemas.newsletters import NewsletterCreate
from app.schemas.settings import Settings, SettingsCreate
from app.services.email_processor import _process_single_email, process_emails


def _setup_test_email_processing(
    db_session: Session,
    newsletter_create_data: NewsletterCreate,
    settings_create_data: SettingsCreate,
) -> tuple[MagicMock, Newsletter, Settings]:
    """Help to set up mocks and data for email processing tests."""
    settings = create_or_update_settings(db_session, settings_create_data)
    newsletter = create_newsletter(db_session, newsletter_create_data)

    mock_mail = MagicMock(spec=imaplib.IMAP4_SSL)
    msg = Message()
    msg["From"] = newsletter_create_data.sender_emails[0]
    msg["Subject"] = "Test Email"
    msg["Message-ID"] = "<test-message-id>"
    msg.set_payload("<html><body><p>Original Body</p></body></html>", "utf-8")
    mock_mail.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])

    return mock_mail, newsletter, settings


def test_process_single_email_with_newsletter_move_folder(db_session: Session):
    """Test that the per-newsletter move_to_folder is used, overriding the global setting."""
    # 1. ARRANGE
    settings_data = SettingsCreate(
        imap_server="test.com",
        imap_username="test",
        imap_password="password",
        move_to_folder="GlobalArchive",
    )
    newsletter_data = NewsletterCreate(
        name="Test Newsletter",
        sender_emails=["test@example.com"],
        move_to_folder="NewsletterArchive",
    )
    mock_mail, newsletter, settings = _setup_test_email_processing(
        db_session, newsletter_data, settings_data
    )
    sender_map = {newsletter.senders[0].email: newsletter}

    # 2. ACT
    _process_single_email("1", mock_mail, db_session, sender_map, settings)

    # 3. ASSERT
    mock_mail.copy.assert_called_once_with("1", "NewsletterArchive")
    mock_mail.store.assert_any_call("1", "+FLAGS", "\\Deleted")


def test_process_single_email_with_global_move_folder(db_session: Session):
    """Test that the global move_to_folder is used when the per-newsletter one is not set."""
    # 1. ARRANGE
    settings_data = SettingsCreate(
        imap_server="test.com",
        imap_username="test",
        imap_password="password",
        move_to_folder="GlobalArchive",
    )
    newsletter_data = NewsletterCreate(
        name="Test Newsletter", sender_emails=["test@example.com"]
    )
    mock_mail, newsletter, settings = _setup_test_email_processing(
        db_session, newsletter_data, settings_data
    )
    sender_map = {newsletter.senders[0].email: newsletter}

    # 2. ACT
    _process_single_email("1", mock_mail, db_session, sender_map, settings)

    # 3. ASSERT
    mock_mail.copy.assert_called_once_with("1", "GlobalArchive")
    mock_mail.store.assert_any_call("1", "+FLAGS", "\\Deleted")


@patch("app.services.email_processor._connect_to_imap")
def test_process_emails_uses_newsletter_search_folder(
    mock_connect_to_imap,
    db_session: Session,
):
    """Test that the per-newsletter search_folder is used, overriding the global setting."""
    # 1. ARRANGE
    settings_data = SettingsCreate(
        imap_server="test.com",
        imap_username="test",
        imap_password="password",
        search_folder="GlobalInbox",
    )
    create_or_update_settings(db_session, settings_data)

    newsletter_data = NewsletterCreate(
        name="Test Newsletter",
        sender_emails=["test@example.com"],
        search_folder="NewsletterInbox",
    )
    create_newsletter(db_session, newsletter_data)

    # Mock the return of _connect_to_imap to avoid a real IMAP connection
    mock_connect_to_imap.return_value = None

    # 2. ACT
    process_emails(db_session)

    # 3. ASSERT
    # Check that _connect_to_imap was called with the newsletter's specific folder
    mock_connect_to_imap.assert_called_once()
    call_args = mock_connect_to_imap.call_args[0]
    assert call_args[1] == "NewsletterInbox"


@patch("app.services.email_processor._connect_to_imap")
def test_process_emails_uses_global_search_folder(
    mock_connect_to_imap,
    db_session: Session,
):
    """Test that the global search_folder is used when the per-newsletter one is not set."""
    # 1. ARRANGE
    settings_data = SettingsCreate(
        imap_server="test.com",
        imap_username="test",
        imap_password="password",
        search_folder="GlobalInbox",
    )
    create_or_update_settings(db_session, settings_data)

    newsletter_data = NewsletterCreate(
        name="Test Newsletter",
        sender_emails=["test@example.com"],
        search_folder=None,  # Explicitly not set
    )
    create_newsletter(db_session, newsletter_data)

    mock_connect_to_imap.return_value = None

    # 2. ACT
    process_emails(db_session)

    # 3. ASSERT
    mock_connect_to_imap.assert_called_once()
    call_args = mock_connect_to_imap.call_args[0]
    assert call_args[1] == "GlobalInbox"


@patch("app.services.email_processor._extract_and_clean_html")
def test_process_single_email_with_content_extraction(
    mock_extract_clean,
    db_session: Session,
):
    """Test that the cleaning function is called when extract_content is True."""
    # 1. ARRANGE
    mock_extract_clean.return_value = {
        "title": "Extracted Title",
        "body": "Extracted Body",
    }
    settings_data = SettingsCreate(
        imap_server="test.com", imap_username="test", imap_password="password"
    )
    newsletter_data = NewsletterCreate(
        name="Test Newsletter",
        sender_emails=["test@example.com"],
        extract_content=True,
    )
    mock_mail, newsletter, settings = _setup_test_email_processing(
        db_session, newsletter_data, settings_data
    )
    sender_map = {newsletter.senders[0].email: newsletter}

    # 2. ACT
    with patch("app.services.email_processor.create_entry") as mock_create_entry:
        _process_single_email("1", mock_mail, db_session, sender_map, settings)

    # 3. ASSERT
    mock_extract_clean.assert_called_once()
    # Check that create_entry was called with the extracted body
    mock_create_entry.assert_called_once()
    entry_create_arg = mock_create_entry.call_args[0][1]
    assert entry_create_arg.body == "Extracted Body"
    # Subject should still come from the email, not the extracted title
    assert entry_create_arg.subject == "Test Email"


def test_process_single_email_with_encoded_from_header(db_session: Session):
    """Test that an encoded From header is correctly decoded for the newsletter name."""
    # 1. ARRANGE
    settings_data = SettingsCreate(
        imap_server="test.com",
        imap_username="test",
        imap_password="password",
        auto_add_new_senders=True,
    )
    settings = create_or_update_settings(db_session, settings_data)

    mock_mail = MagicMock(spec=imaplib.IMAP4_SSL)
    msg = Message()
    # "Кирилл" in Cyrillic, base64 encoded for UTF-8
    from_header = "=?utf-8?B?0JrQuNGA0LjQu9C7?= <test@example.com>"
    msg["From"] = from_header
    msg["Subject"] = "Test Email"
    msg["Message-ID"] = "<test-message-id-encoded-from>"
    msg.set_payload("<html><body><p>Body</p></body></html>", "utf-8")
    mock_mail.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])

    sender_map = {}  # empty, to trigger auto-add

    # 2. ACT
    _process_single_email("1", mock_mail, db_session, sender_map, settings)

    # 3. ASSERT
    from app.crud.newsletters import get_newsletters

    newsletters = get_newsletters(db_session)
    assert len(newsletters) == 1
    assert newsletters[0].name == "Кирилл"
    assert newsletters[0].senders[0].email == "test@example.com"


def test_process_single_email_with_null_bytes_in_body(db_session: Session):
    """Test that an email with NULL bytes in its body is handled gracefully.

    - The NULL bytes should be stripped.
    - Content extraction should still be attempted.
    - If it fails, an error is logged and the raw body is used.
    """
    # 1. ARRANGE
    settings_data = SettingsCreate(
        imap_server="test.com", imap_username="test", imap_password="password"
    )
    newsletter_data = NewsletterCreate(
        name="Test Newsletter",
        sender_emails=["test@example.com"],
        extract_content=True,  # Important: we want to test the extraction path
    )
    settings = create_or_update_settings(db_session, settings_data)
    newsletter = create_newsletter(db_session, newsletter_data)

    mock_mail = MagicMock(spec=imaplib.IMAP4_SSL)
    msg = Message()
    msg["From"] = "test@example.com"
    msg["Subject"] = "Test Email with NULLs"
    msg["Message-ID"] = "<test-message-id-nulls>"
    # The body contains NULL bytes that would cause readability-lxml to crash
    body_with_nulls = "<html><body><p>Hello\x00 World</p></body></html>"
    msg.set_payload(body_with_nulls, "utf-8")
    mock_mail.fetch.return_value = ("OK", [(b"1 (RFC822)", msg.as_bytes())])

    sender_map = {newsletter.senders[0].email: newsletter}

    # 2. ACT & ASSERT
    with (
        patch("app.services.email_processor.logger") as mock_logger,
        patch("app.services.email_processor.create_entry") as mock_create_entry,
    ):
        # We mock readability.Document to simulate a failure *after* our sanitization
        # to ensure the try/except block is also working.
        with patch("app.services.email_processor.Document") as mock_document:
            mock_document.side_effect = ValueError("Simulated lxml failure")
            _process_single_email("1", mock_mail, db_session, sender_map, settings)

            # Assert that the logger was called with a warning
            mock_logger.warning.assert_called_once()
            assert "Failed to extract content" in mock_logger.warning.call_args[0][0]

        # Check that an entry was still created
        mock_create_entry.assert_called_once()
        entry_create_arg = mock_create_entry.call_args[0][1]

        # The body should be the original (but decoded) body, since extraction failed
        # Note: _get_email_body will decode the payload.
        assert "Hello\x00 World" in entry_create_arg.body


# More newsletters than the HTTP page size (100) that get_newsletters defaults to.
MANY_NEWSLETTERS = 120


def _fake_mailbox(senders: list[str]) -> MagicMock:
    """Build a fake IMAP connection holding one unseen email per sender."""
    messages = {}
    for i, sender in enumerate(senders, start=1):
        msg = Message()
        msg["From"] = sender
        msg["Subject"] = f"Issue from {sender}"
        msg["Message-ID"] = f"<msg-{i}@example.com>"
        msg.set_payload("<html><body><p>Body</p></body></html>", "utf-8")
        messages[str(i).encode()] = msg.as_bytes()

    mail = MagicMock(spec=imaplib.IMAP4_SSL)
    mail.search.return_value = ("OK", [b" ".join(messages)])
    mail.fetch.side_effect = lambda num, _parts: (
        "OK",
        [(num + b" (BODY[])", messages[num])],
    )
    return mail


def _create_many_newsletters(db_session: Session, auto_add: bool) -> list[str]:
    create_or_update_settings(
        db_session,
        SettingsCreate(
            imap_server="test.com",
            imap_username="test",
            imap_password="password",
            mark_as_read=True,
            auto_add_new_senders=auto_add,
        ),
    )
    senders = [f"sender{i}@example.com" for i in range(MANY_NEWSLETTERS)]
    for i, sender in enumerate(senders):
        create_newsletter(
            db_session, NewsletterCreate(name=f"Newsletter {i}", sender_emails=[sender])
        )
    return senders


def _entries_per_sender() -> dict[str, int]:
    """Count stored entries per sender using a fresh session.

    A fresh session is used because an IntegrityError mid-run leaves the
    processor's session needing a rollback.
    """
    with Session(engine) as fresh:
        rows = (
            fresh.query(Sender.email, func.count(Entry.id))
            .join(Newsletter, Sender.newsletter_id == Newsletter.id)
            .outerjoin(Entry, Entry.newsletter_id == Newsletter.id)
            .group_by(Sender.email)
            .all()
        )
    return dict(rows)


@patch("app.services.email_processor._connect_to_imap")
def test_process_emails_matches_senders_beyond_first_100_newsletters(
    mock_connect_to_imap, db_session: Session
):
    """Every known sender is matched, not auto-added, however many newsletters exist.

    Regression: process_emails called get_newsletters(db) and inherited its
    HTTP page size of 100, so senders of newsletters past the first 100 were
    treated as unknown. Auto-add then tried to re-insert an existing sender and
    hit UNIQUE constraint failed: senders.email, aborting the whole folder.
    """
    senders = _create_many_newsletters(db_session, auto_add=True)
    mock_connect_to_imap.return_value = _fake_mailbox(senders)

    with patch("app.services.email_processor.logger") as mock_logger:
        process_emails(db_session)

    mock_logger.error.assert_not_called()
    entries = _entries_per_sender()
    assert len(entries) == MANY_NEWSLETTERS  # nothing was auto-added
    assert entries == {sender: 1 for sender in senders}


@patch("app.services.email_processor._connect_to_imap")
def test_process_emails_without_auto_add_ingests_beyond_first_100_newsletters(
    mock_connect_to_imap, db_session: Session
):
    """With auto-add off, newsletters past the first 100 are still ingested.

    Unknown senders must still be left unread so their mail isn't consumed.
    """
    senders = _create_many_newsletters(db_session, auto_add=False)
    unknown = "stranger@example.com"
    mail = _fake_mailbox([*senders, unknown])
    mock_connect_to_imap.return_value = mail

    process_emails(db_session)

    assert _entries_per_sender() == {sender: 1 for sender in senders}
    unknown_num = str(len(senders) + 1).encode()
    assert (unknown_num, "+FLAGS", "\\Seen") not in [
        c.args for c in mail.store.call_args_list
    ]
