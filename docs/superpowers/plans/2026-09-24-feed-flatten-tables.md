# Flatten Layout Tables in Feed Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve Atom feed `<content>` in which newsletter layout tables are flattened to `<div>`s, computed once per entry and stored in a new `entries.feed_body` column, behind a backend-only switch.

**Architecture:** A pure transform (`app/services/feed_html.py`) classifies each `<table>` as layout or data and converts layout tables to `<div>`s. `create_entry` stores its output in `entries.feed_body`; a one-shot startup job backfills existing rows; the feed generator serves `feed_body` when `settings.flatten_feed_tables` is on and the column is filled, `body` otherwise.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0, Alembic, BeautifulSoup 4 (`html.parser`), feedgen 1.0.0, APScheduler, pydantic-settings, pytest, ruff, uv.

**Spec:** `/Users/mcable/src/LetterFeed/.worktrees/feed-flatten-tables/docs/superpowers/specs/2026-09-24-feed-flatten-tables-design.md` — read it before starting any task.

## Global Constraints

- **Working directory:** `/Users/mcable/src/LetterFeed/.worktrees/feed-flatten-tables`. `cd` there before the first write. Never write in `/Users/mcable/src/LetterFeed` (the main checkout). Every subagent dispatch must state this absolute path **and** tell the agent to `cd` there before its first write.
- Branch `feat/feed-flatten-tables` (based on `origin/deploy/prod` @ 242450d; spec commit b69ccd2). It has no upstream on purpose. If pushing: `git push -u origin feat/feed-flatten-tables`. Never push to `deploy/prod` or `master`.
- **Fork-only.** Never open an upstream PR, issue or comment.
- New Alembic migration: `down_revision = "a3f1c2d4e5b6"`.
- Backend commands run from `backend/`: `uv sync --group test`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check app`. Use `uv run python`, never bare `python3`.
- TDD: every test is watched failing on unmodified code, for the expected reason, before its implementation is written.
- Any claim that tests or lint pass must include the command and its **full** output (not a `tail`).
- Baseline before this plan (2026-09-24): `uv run pytest -q` → `109 passed`; `ruff check .` → `All checks passed!`; `ruff format --check app` → `47 files already formatted`.
- Transform rules, stripped attribute list and backfill batch size (50) are copied from the spec verbatim below; do not change them.
- The stored `body`, the `/entries/{id}` page and the API/UI entry schemas stay unchanged. Do **not** add `feed_body` to `app/schemas/entries.py`.
- Don't commit `backend/.venv`, `backend/test.db` or anything under `frontend/node_modules`.
- Commit messages end with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `backend/app/services/feed_html.py` | Create | Pure `flatten_layout_tables(html) -> str`. No DB, no settings. |
| `backend/app/tests/services/test_feed_html.py` | Create | Unit tests for the transform. |
| `backend/app/models/entries.py` | Modify | Add `feed_body = Column(Text, nullable=True)`. |
| `backend/alembic/versions/b7e2f4a9c1d3_add_feed_body_to_entries.py` | Create | Add/drop `entries.feed_body`. |
| `backend/app/crud/entries.py` | Modify | `create_entry` fills `feed_body`. |
| `backend/app/tests/test_crud.py` | Modify | Test that `create_entry` fills `feed_body`. |
| `backend/app/core/config.py` | Modify | `flatten_feed_tables: bool = True`. |
| `backend/app/services/feed_generator.py` | Modify | `_entry_content(entry)` picks `feed_body` or `body`. |
| `backend/app/tests/services/test_feed_generator.py` | Modify | Switch on/off/null tests for both feeds; config default/env test. |
| `backend/app/services/feed_body_backfill.py` | Create | `backfill_feed_bodies(db, batch_size=50) -> int`. |
| `backend/app/tests/services/test_feed_body_backfill.py` | Create | Backfill tests. |
| `backend/app/core/scheduler.py` | Modify | `backfill_job()` wrapper and its `date` job `id="feed_body_backfill"`. |
| `backend/app/tests/test_core.py` | Modify | Scheduler registration and `backfill_job` tests. |

---

### Task 1: The flattening transform

**Files:**
- Create: `backend/app/services/feed_html.py`
- Test: `backend/app/tests/services/test_feed_html.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.services.feed_html.flatten_layout_tables(html: str) -> str`. Never raises; on any exception logs a warning with traceback and returns `html` unchanged. Empty/whitespace-only input is returned unchanged. Tasks 2 and 4 import it; Task 4's tests patch `app.services.feed_html.BeautifulSoup` to force a failure, so the module must reference `BeautifulSoup` by that module-level name.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/tests/services/test_feed_html.py`:

```python
import logging
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from app.services.feed_html import flatten_layout_tables


def _tables(html: str) -> int:
    """Count the <table> elements in `html`."""
    return len(BeautifulSoup(html, "html.parser").find_all("table"))


# Each fixture trips exactly one rule: the others would classify it as data.
@pytest.mark.parametrize(
    "html",
    [
        pytest.param(
            '<table role="presentation"><tr><th>A</th><th>B</th></tr>'
            "<tr><td>1</td><td>2</td></tr></table>",
            id="rule1-role-presentation",
        ),
        pytest.param(
            '<table role="none"><tr><th>A</th><th>B</th></tr>'
            "<tr><td>1</td><td>2</td></tr></table>",
            id="rule1-role-none",
        ),
        pytest.param(
            "<table><tr><th>A</th><th>B</th></tr>"
            '<tr><td><table role="presentation"><tr><td>x</td></tr></table></td>'
            "<td>2</td></tr></table>",
            id="rule2-contains-table",
        ),
        pytest.param(
            "<table><tr><th>A</th><th>B</th></tr></table>",
            id="rule3-single-row",
        ),
        pytest.param(
            "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>",
            id="rule4-no-row-with-two-cells",
        ),
        pytest.param(
            "<table><tr><td><p>A</p></td><td>B</td></tr>"
            "<tr><td>1</td><td>2</td></tr></table>",
            id="rule5-block-content-no-th",
        ),
    ],
)
def test_layout_table_rules_convert_to_divs(html):
    """Each layout rule, on its own, turns the table into divs."""
    out = flatten_layout_tables(html)
    assert _tables(out) == 0
    soup = BeautifulSoup(out, "html.parser")
    assert soup.find(["tr", "td", "th", "tbody"]) is None
    assert soup.find("div") is not None


def test_data_table_is_kept():
    """A header row plus rows of text is a data table and stays as is."""
    html = (
        "<table><tr><th>Ticker</th><th>Price</th></tr>"
        "<tr><td>ABC</td><td>1.00</td></tr>"
        "<tr><td>XYZ</td><td>2.50</td></tr></table>"
    )
    assert flatten_layout_tables(html) == html


def test_data_table_nested_in_layout_table_survives():
    """Converting a layout table never reaches into a nested data table."""
    data = (
        "<table><tr><th>Ticker</th><th>Price</th></tr>"
        "<tr><td>ABC</td><td>1.00</td></tr></table>"
    )
    html = (
        '<table role="presentation" width="600"><tbody><tr>'
        f'<td valign="top">{data}</td></tr></tbody></table>'
    )
    out = flatten_layout_tables(html)
    assert out == f'<div role="presentation"><div><div>{data}</div></div></div>'


def test_mailchimp_style_nesting_flattens_every_level():
    """Every level of email-style nested layout tables becomes a div."""
    html = (
        '<table align="center" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" bgcolor="#eee"><tbody><tr><td align="center" valign="top">'
        '<table role="presentation" width="600"><tbody><tr><td>'
        '<table width="100%"><tr><td><img src="https://example.test/p.jpg" '
        'width="560"></td></tr></table>'
        "</td></tr></tbody></table></td></tr></tbody></table>"
    )
    out = flatten_layout_tables(html)
    assert _tables(out) == 0
    assert '<img src="https://example.test/p.jpg" width="560"/>' in out


def test_converted_elements_lose_layout_attributes_but_keep_others():
    """Table-layout attributes go; style, class, id and the rest stay."""
    html = (
        '<table role="presentation" align="center" width="600" height="10" '
        'bgcolor="#fff" background="bg.png" cellpadding="0" cellspacing="0" '
        'border="0" style="color: red" class="wrap" id="outer">'
        '<tr valign="top" style="s1"><td colspan="2" rowspan="1" align="left" '
        'class="cell">x</td></tr></table>'
    )
    out = flatten_layout_tables(html)
    soup = BeautifulSoup(out, "html.parser")
    outer = soup.find(id="outer")
    assert outer.name == "div"
    assert outer.attrs == {
        "role": "presentation",
        "style": "color: red",
        "class": ["wrap"],
        "id": "outer",
    }
    row, cell = outer.find_all("div")
    assert row.attrs == {"style": "s1"}
    assert cell.attrs == {"class": ["cell"]}


def test_tracking_pixels_removed_and_real_images_kept():
    """Images 2px or smaller in either dimension are removed."""
    html = (
        '<p><img src="t1.gif" width="1" height="1">'
        '<img src="t2.gif" height="2">'
        '<img src="t0.gif" width="0">'
        '<img src="photo.jpg" width="600">'
        '<img src="auto.jpg" width="auto">'
        '<img src="plain.jpg"></p>'
    )
    out = flatten_layout_tables(html)
    for gone in ("t1.gif", "t2.gif", "t0.gif"):
        assert gone not in out
    for kept in ("photo.jpg", "auto.jpg", "plain.jpg"):
        assert kept in out


def test_html_without_tables_is_unchanged():
    """HTML with no tables comes back as it went in."""
    html = '<p>Hi <b>there</b>, <a href="https://example.test/">link</a></p>'
    assert flatten_layout_tables(html) == html


@pytest.mark.parametrize("html", ["", "   \n\t "])
def test_empty_body_is_returned_unchanged(html):
    """Empty or whitespace-only input is returned untouched."""
    assert flatten_layout_tables(html) == html


def test_output_is_a_fragment():
    """No html or body wrapper is added."""
    out = flatten_layout_tables('<table role="none"><tr><td>x</td></tr></table>')
    assert "<html" not in out and "<body" not in out


def test_malformed_html_does_not_raise():
    """Unclosed tags are parsed leniently rather than raising."""
    out = flatten_layout_tables("<table><tr><td><div>unclosed<table><tr><td>x")
    assert "x" in out


def test_exception_inside_transform_returns_input_and_logs(caplog):
    """Any failure logs a warning with traceback and returns the input."""
    html = '<table role="none"><tr><td>x</td></tr></table>'
    with (
        patch("app.services.feed_html.BeautifulSoup", side_effect=RuntimeError("boom")),
        caplog.at_level(logging.WARNING, logger="app.services.feed_html"),
    ):
        assert flatten_layout_tables(html) == html
    record = next(r for r in caplog.records if r.name == "app.services.feed_html")
    assert record.levelno == logging.WARNING
    assert record.exc_info is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`): `uv run pytest app/tests/services/test_feed_html.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'app.services.feed_html'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/feed_html.py`:

```python
from bs4 import BeautifulSoup

from app.core.logging import get_logger

"""Rewrite newsletter HTML for feed readers that treat every table as data."""

logger = get_logger(__name__)

# A cell holding any of these is laying out content, not holding a datum.
_BLOCK_TAGS = [
    "img",
    "div",
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "blockquote",
    "table",
]

# Table-layout attributes that mean nothing on a <div>.
_LAYOUT_ATTRS = (
    "align",
    "valign",
    "width",
    "height",
    "bgcolor",
    "background",
    "cellpadding",
    "cellspacing",
    "border",
    "colspan",
    "rowspan",
)


def _own(table, names):
    """Return descendants of `table` named `names` that no nested table owns."""
    return [el for el in table.find_all(names) if el.find_parent("table") is table]


def _is_layout_table(table, rows, cells) -> bool:
    """Apply the spec's rules 1-5, in order; any match makes it a layout table."""
    if table.get("role", "").strip().lower() in ("presentation", "none"):
        return True
    if table.find("table") is not None:
        return True
    if len(rows) < 2:
        return True
    if not any(
        sum(1 for c in cells if c.find_parent("tr") is row) >= 2 for row in rows
    ):
        return True
    if not any(c.name == "th" for c in cells) and any(
        c.find(_BLOCK_TAGS) is not None for c in cells
    ):
        return True
    return False


def _is_tracking_pixel(img) -> bool:
    for attr in ("width", "height"):
        try:
            if int(str(img.get(attr, "")).strip()) <= 2:
                return True
        except ValueError:
            pass
    return False


def _flatten(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Classify every table, and collect what it owns, against the unmodified
    # tree: once an inner table is renamed to <div>, find_parent("table") would
    # attribute its rows to the outer table.
    layout = []
    for table in soup.find_all("table"):
        rows = _own(table, "tr")
        cells = _own(table, ["td", "th"])
        if _is_layout_table(table, rows, cells):
            sections = _own(table, ["tbody", "thead", "tfoot"])
            layout.append((table, sections, rows, cells))

    for table, sections, rows, cells in layout:
        for section in sections:
            section.unwrap()
        for el in (table, *rows, *cells):
            el.name = "div"
            for attr in _LAYOUT_ATTRS:
                el.attrs.pop(attr, None)

    for img in soup.find_all("img"):
        if _is_tracking_pixel(img):
            img.decompose()

    return str(soup)


def flatten_layout_tables(html: str) -> str:
    """Convert layout tables to <div>s, keep data tables, drop tracking pixels.

    Never raises: on any failure the input is returned unchanged.
    """
    if not html or not html.strip():
        return html
    try:
        return _flatten(html)
    except Exception:
        logger.warning("Could not flatten layout tables", exc_info=True)
        return html
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest app/tests/services/test_feed_html.py -v`
Expected: all tests PASS (17 items including parametrized cases).

- [ ] **Step 5: Lint**

Run: `uv run ruff check . && uv run ruff format --check app`
Expected: `All checks passed!` and `N files already formatted`. If format reports a file, run `uv run ruff format app` and re-check.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/feed_html.py backend/app/tests/services/test_feed_html.py
git commit -m "feat: flatten newsletter layout tables for feed readers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `entries.feed_body` column, migration, and filling it at ingestion

**Files:**
- Modify: `backend/app/models/entries.py` (add column after `body`)
- Create: `backend/alembic/versions/b7e2f4a9c1d3_add_feed_body_to_entries.py`
- Modify: `backend/app/crud/entries.py` (`create_entry`)
- Test: `backend/app/tests/test_crud.py`

**Interfaces:**
- Consumes: `flatten_layout_tables(html: str) -> str` from Task 1.
- Produces: `Entry.feed_body` (`Text`, nullable; `None` = no flattened copy yet). `create_entry(db, entry, newsletter_id)` returns an `Entry` whose `feed_body == flatten_layout_tables(entry.body)`. Alembic head becomes `b7e2f4a9c1d3`.

- [ ] **Step 1: Write the failing test**

Append to `backend/app/tests/test_crud.py` (`uuid`, `Session`, `create_entry`, `create_newsletter`, `EntryCreate`, `NewsletterCreate` are already imported there):

```python
def test_create_entry_fills_feed_body_with_flattened_body(db_session: Session):
    """New entries store a flattened copy for feeds and keep the original body."""
    newsletter = create_newsletter(
        db_session,
        NewsletterCreate(
            name="Flatten", sender_emails=[f"flat_{uuid.uuid4()}@test.com"]
        ),
    )
    body = '<table role="presentation"><tr><td><p>Hello</p></td></tr></table>'

    entry = create_entry(
        db_session,
        EntryCreate(subject="Flat", body=body, message_id=f"<{uuid.uuid4()}@test.com>"),
        newsletter.id,
    )

    assert entry.body == body
    assert (
        entry.feed_body
        == '<div role="presentation"><div><div><p>Hello</p></div></div></div>'
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest app/tests/test_crud.py::test_create_entry_fills_feed_body_with_flattened_body -v`
Expected: FAIL with `AttributeError: 'Entry' object has no attribute 'feed_body'`.

- [ ] **Step 3: Add the model column**

In `backend/app/models/entries.py`, after `body = Column(Text)`:

```python
    # Body with layout tables flattened for feed readers; None until filled.
    feed_body = Column(Text, nullable=True)
```

- [ ] **Step 4: Run the test again**

Run: `uv run pytest app/tests/test_crud.py::test_create_entry_fills_feed_body_with_flattened_body -v`
Expected: FAIL, now with `assert None == '<div role="presentation">...'` (column exists, nothing fills it).

- [ ] **Step 5: Fill it in `create_entry`**

In `backend/app/crud/entries.py` add this import directly after `from app.schemas.entries import EntryCreate` (isort order: `app.core`, `app.models`, `app.schemas`, `app.services`):

```python
from app.services.feed_html import flatten_layout_tables
```

and change the `db_entry = ...` line in `create_entry` to:

```python
    db_entry = Entry(
        id=generate(),
        **entry.model_dump(),
        feed_body=flatten_layout_tables(entry.body),
        newsletter_id=newsletter_id,
    )
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest app/tests/test_crud.py -v`
Expected: all PASS.

- [ ] **Step 7: Write the migration**

Create `backend/alembic/versions/b7e2f4a9c1d3_add_feed_body_to_entries.py`:

```python
"""add feed_body to entries

Revision ID: b7e2f4a9c1d3
Revises: a3f1c2d4e5b6
Create Date: 2026-09-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2f4a9c1d3'
down_revision: Union[str, Sequence[str], None] = 'a3f1c2d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('entries', sa.Column('feed_body', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('entries', 'feed_body')
```

(Quoting style matches the existing migrations; `alembic/` is outside `ruff format --check app`.)

- [ ] **Step 8: Verify the migration against a scratch database**

No test suite exercises Alembic, so check it by hand. From `backend/`:

```bash
export SCRATCH_DB="$(mktemp -d)/mig.db"
LETTERFEED_DATABASE_URL="sqlite:///$SCRATCH_DB" uv run alembic heads
LETTERFEED_DATABASE_URL="sqlite:///$SCRATCH_DB" uv run alembic upgrade head
uv run python -c "import sqlite3,os; print([r[1] for r in sqlite3.connect(os.environ['SCRATCH_DB']).execute('pragma table_info(entries)')])"
LETTERFEED_DATABASE_URL="sqlite:///$SCRATCH_DB" uv run alembic downgrade a3f1c2d4e5b6
uv run python -c "import sqlite3,os; print([r[1] for r in sqlite3.connect(os.environ['SCRATCH_DB']).execute('pragma table_info(entries)')])"
```

Expected: `heads` prints exactly one head, `b7e2f4a9c1d3 (head)`. After upgrade the column list includes `feed_body`; after downgrade it does not. Paste the output in the task report.

- [ ] **Step 9: Full suite and lint**

Run: `uv run pytest -q`, then `uv run ruff check .` and `uv run ruff format --check app`.
Expected: all pass (baseline 109 + Task 1's tests + 1). Paste full output.

- [ ] **Step 10: Commit**

```bash
git add backend/app/models/entries.py backend/app/crud/entries.py backend/app/tests/test_crud.py backend/alembic/versions/b7e2f4a9c1d3_add_feed_body_to_entries.py
git commit -m "feat: store a flattened feed_body for each new entry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The switch and serving `feed_body` in feeds

**Files:**
- Modify: `backend/app/core/config.py` (add field after `master_feed_limit`)
- Modify: `backend/app/services/feed_generator.py` (`_add_entries_to_feed`, new `_entry_content`)
- Test: `backend/app/tests/services/test_feed_generator.py`

**Interfaces:**
- Consumes: `Entry.feed_body` and `create_entry` filling it (Task 2).
- Produces: `Settings.flatten_feed_tables: bool = True`, read from env `LETTERFEED_FLATTEN_FEED_TABLES` via the existing `env_prefix`. `feed_generator._entry_content(entry: Entry) -> str`.

The three behaviours are driven in by three separate red/green cycles so that each test fails on the code as it stands at that moment (the switch-off and null tests would pass trivially against the original code).

- [ ] **Step 1: Add test helpers and the switch-on test**

Append to `backend/app/tests/services/test_feed_generator.py`:

```python
FLAT = "<div>flattened</div>"


def _patched_settings(**update):
    """Patch the feed generator's settings with arbitrary field overrides."""
    return patch.object(feed_generator, "settings", settings.model_copy(update=update))


def _render(db: Session, which: str, newsletter) -> bytes:
    """Render the per-newsletter or the master feed."""
    if which == "newsletter":
        return generate_feed(db, newsletter.id)
    return generate_master_feed(db)


def _content_by_id(feed_xml: bytes) -> dict[str, str]:
    """Map each Atom entry's LetterFeed id to its <content> text."""
    root = ET.fromstring(feed_xml)
    return {
        entry.find("atom:id", ATOM_NS).text.removeprefix(
            "urn:letterfeed:entry:"
        ): entry.find("atom:content", ATOM_NS).text
        for entry in root.findall("atom:entry", ATOM_NS)
    }


def _seed_one(db: Session, feed_body: str | None):
    """One entry whose stored feed_body is overwritten with `feed_body`."""
    newsletter, (entry_id,) = _seed_newsletter_with_entries(db, count=1)
    entry = db.get(Entry, entry_id)
    entry.feed_body = feed_body
    db.commit()
    return newsletter, entry


@pytest.mark.parametrize("which", ["newsletter", "master"])
def test_feed_serves_feed_body_when_switch_on(db_session: Session, which):
    """With the switch on, feeds publish the flattened feed_body."""
    newsletter, entry = _seed_one(db_session, FLAT)

    with _patched_settings(flatten_feed_tables=True):
        content = _content_by_id(_render(db_session, which, newsletter))

    assert content[entry.id] == FLAT
```

and add `from app.models.entries import Entry` to the imports at the top, directly after `from app.crud.newsletters import create_newsletter`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest app/tests/services/test_feed_generator.py -k switch_on -v`
Expected: 2 FAIL, `AssertionError: assert '<p>Body 0</p>' == '<div>flattened</div>'`.

- [ ] **Step 3: Minimal implementation**

In `backend/app/services/feed_generator.py`, add above `_add_entries_to_feed`:

```python
def _entry_content(entry: Entry) -> str:
    """Return the HTML to publish as an entry's feed content."""
    return entry.feed_body
```

and in `_add_entries_to_feed` replace `fe.content(entry.body, type="html")` with:

```python
        fe.content(_entry_content(entry), type="html")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest app/tests/services/test_feed_generator.py -k switch_on -v`
Expected: 2 PASS.

- [ ] **Step 5: Null-`feed_body` test**

Append:

```python
@pytest.mark.parametrize("which", ["newsletter", "master"])
def test_feed_serves_body_when_feed_body_is_null(db_session: Session, which):
    """An entry not yet backfilled falls back to its original body."""
    newsletter, entry = _seed_one(db_session, None)

    with _patched_settings(flatten_feed_tables=True):
        content = _content_by_id(_render(db_session, which, newsletter))

    assert content[entry.id] == entry.body
```

Run: `uv run pytest app/tests/services/test_feed_generator.py -k feed_body_is_null -v`
Expected: 2 FAIL with `AttributeError: 'NoneType' object has no attribute 'text'` in `_content_by_id`: given `None` content, feedgen omits the `<content>` element (the entry still has its alternate link, so feedgen doesn't raise).

- [ ] **Step 6: Fall back to `body`**

```python
def _entry_content(entry: Entry) -> str:
    """Return the HTML to publish as an entry's feed content."""
    if entry.feed_body is not None:
        return entry.feed_body
    return entry.body
```

Run: `uv run pytest app/tests/services/test_feed_generator.py -v`
Expected: all PASS.

- [ ] **Step 7: Switch-off test and the config test**

Append:

```python
@pytest.mark.parametrize("which", ["newsletter", "master"])
def test_feed_serves_body_when_switch_off(db_session: Session, which):
    """With the switch off, feeds publish the original body."""
    newsletter, entry = _seed_one(db_session, FLAT)

    with _patched_settings(flatten_feed_tables=False):
        content = _content_by_id(_render(db_session, which, newsletter))

    assert content[entry.id] == entry.body


def test_flatten_feed_tables_defaults_on_and_reads_env(monkeypatch):
    """The switch is on by default and LETTERFEED_FLATTEN_FEED_TABLES turns it off."""
    from app.core.config import Settings

    monkeypatch.delenv("LETTERFEED_FLATTEN_FEED_TABLES", raising=False)
    assert Settings(_env_file=None).flatten_feed_tables is True

    monkeypatch.setenv("LETTERFEED_FLATTEN_FEED_TABLES", "false")
    assert Settings(_env_file=None).flatten_feed_tables is False
```

Run: `uv run pytest app/tests/services/test_feed_generator.py -k "switch_off or defaults_on" -v`
Expected: 3 FAIL — the two feed tests with `assert '<div>flattened</div>' == '<p>Body 0</p>'`, the config test with `AttributeError: 'Settings' object has no attribute 'flatten_feed_tables'`.

- [ ] **Step 8: Add the setting and honour it**

In `backend/app/core/config.py`, after the `master_feed_limit` field:

```python
    # Serve entries' flattened feed_body in feeds (see app/services/feed_html.py).
    flatten_feed_tables: bool = True
```

In `backend/app/services/feed_generator.py`:

```python
def _entry_content(entry: Entry) -> str:
    """Return the HTML to publish as an entry's feed content."""
    if settings.flatten_feed_tables and entry.feed_body is not None:
        return entry.feed_body
    return entry.body
```

- [ ] **Step 9: Full suite and lint**

Run: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check app`.
Expected: all pass. Paste full output.

- [ ] **Step 10: Commit**

```bash
git add backend/app/core/config.py backend/app/services/feed_generator.py backend/app/tests/services/test_feed_generator.py
git commit -m "feat: serve flattened feed bodies behind LETTERFEED_FLATTEN_FEED_TABLES

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Backfill existing entries at startup

**Files:**
- Create: `backend/app/services/feed_body_backfill.py`
- Test: `backend/app/tests/services/test_feed_body_backfill.py`
- Modify: `backend/app/core/scheduler.py`
- Test: `backend/app/tests/test_core.py`

**Interfaces:**
- Consumes: `flatten_layout_tables` (Task 1), `Entry.feed_body` (Task 2).
- Produces: `app.services.feed_body_backfill.backfill_feed_bodies(db: Session, batch_size: int = 50) -> int` (number of entries filled). `app.core.scheduler.backfill_job() -> None`, registered as an APScheduler `date` job with `id="feed_body_backfill"`.

Batches walk `Entry.id` in ascending order (keyset: `id > last_id`), so the loop terminates even if a row somehow stays null.

- [ ] **Step 1: Write the failing backfill tests**

Create `backend/app/tests/services/test_feed_body_backfill.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest app/tests/services/test_feed_body_backfill.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'app.services.feed_body_backfill'`.

- [ ] **Step 3: Implement the backfill**

Create `backend/app/services/feed_body_backfill.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest app/tests/services/test_feed_body_backfill.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Write the failing scheduler tests**

In `backend/app/tests/test_core.py`, append (`create_or_update_settings`, `SettingsCreate`, `datetime`, `patch` and `Session` are already imported there; `get_settings` raises without a settings row, so the test creates one as the existing scheduler test does):

```python
@patch("app.core.scheduler.SessionLocal")
@patch("app.core.scheduler.scheduler")
@patch("app.core.scheduler.datetime")
def test_start_scheduler_registers_feed_body_backfill(
    mock_datetime, mock_scheduler, mock_session_local, db_session: Session
):
    """The feed_body backfill runs once, at startup."""
    fixed_now = datetime(2025, 10, 20, 12, 0, 0)
    mock_datetime.now.return_value = fixed_now
    mock_session_local.return_value = db_session
    mock_scheduler.running = False
    create_or_update_settings(
        db_session,
        SettingsCreate(
            imap_server="imap.test.com",
            imap_username="test@test.com",
            imap_password="password",
        ),
    )

    from app.core.scheduler import backfill_job, start_scheduler_with_interval

    start_scheduler_with_interval()

    mock_scheduler.add_job.assert_any_call(
        backfill_job,
        "date",
        run_date=fixed_now,
        id="feed_body_backfill",
        replace_existing=True,
    )


@patch("app.core.scheduler.SessionLocal")
@patch("app.core.scheduler.backfill_feed_bodies")
def test_backfill_job(mock_backfill, mock_session_local, db_session: Session):
    """The backfill job runs the backfill on a fresh session."""
    mock_session_local.return_value = db_session
    from app.core.scheduler import backfill_job

    backfill_job()
    mock_backfill.assert_called_once_with(db_session)


@patch("app.core.scheduler.SessionLocal")
@patch("app.core.scheduler.backfill_feed_bodies", side_effect=RuntimeError("x"))
def test_backfill_job_logs_instead_of_raising(
    mock_backfill, mock_session_local, db_session: Session
):
    """A failing backfill is logged, not raised into the scheduler."""
    mock_session_local.return_value = db_session
    from app.core.scheduler import backfill_job

    backfill_job()  # must not raise
```

- [ ] **Step 6: Run to verify they fail**

Run: `uv run pytest app/tests/test_core.py -k "backfill" -v`
Expected: 3 FAIL/ERROR — `ImportError: cannot import name 'backfill_job'` for the first, and `AttributeError: <module 'app.core.scheduler'> does not have the attribute 'backfill_feed_bodies'` for the patch-based two.

- [ ] **Step 7: Implement the job and register it**

In `backend/app/core/scheduler.py`, add the import beside the existing ones:

```python
from app.services.feed_body_backfill import backfill_feed_bodies
```

Add after `job()`:

```python
def backfill_job():
    """Fill feed_body for entries that predate it, as a one-off job."""
    db = SessionLocal()
    try:
        backfill_feed_bodies(db)
    except Exception as e:
        logger.error(f"Error in feed body backfill: {e}", exc_info=True)
    finally:
        db.close()
```

In `start_scheduler_with_interval`, inside `if not scheduler.running:`, add **before** the `initial_email_check` `add_job` (the existing `test_start_scheduler_with_interval` asserts that `initial_email_check` is the *last* `add_job` call, so it must stay last):

```python
            scheduler.add_job(
                backfill_job,
                "date",
                run_date=datetime.now(),
                id="feed_body_backfill",
                replace_existing=True,
            )
```

- [ ] **Step 8: Run to verify they pass**

Run: `uv run pytest app/tests/test_core.py -v`
Expected: all PASS, including the unchanged `test_start_scheduler_with_interval`.

- [ ] **Step 9: Full suite and lint**

Run: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check app`.
Expected: all pass. Paste full output.

Note: `TestClient(app)` runs the lifespan, which starts the real scheduler once per test session, so `backfill_job` and `initial_email_check` both fire in a background thread against `test.db`. Both catch and log their own errors. If a stray "no such table" error line appears in captured logs but tests pass, that is this pre-existing pattern, not a failure.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/feed_body_backfill.py backend/app/tests/services/test_feed_body_backfill.py backend/app/core/scheduler.py backend/app/tests/test_core.py
git commit -m "feat: backfill feed_body for existing entries at startup

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Final verification

No new code. This gates the branch before it is offered for merging into `deploy/prod`.

- [ ] **Step 1: Full gauntlet from a clean sync**

From `backend/`:

```bash
uv sync --group test
uv run pytest
uv run ruff check .
uv run ruff format --check app
```

Paste the **full** output of each. Read all of it, not a tail.

- [ ] **Step 2: Single Alembic head on the final tree**

```bash
LETTERFEED_DATABASE_URL="sqlite:///$(mktemp -d)/h.db" uv run alembic heads
```

Expected: exactly `b7e2f4a9c1d3 (head)`.

- [ ] **Step 3: Diff review against the spec**

```bash
git diff --stat 242450d..HEAD
git diff 242450d..HEAD -- backend/app/schemas backend/app/routers
```

Expected: the second command prints nothing (schemas and routers untouched, so `/entries/{id}` and the API still use `body`). Walk the spec's Testing list and confirm each bullet maps to a test by name.

- [ ] **Step 4: Hand-off note for the Current replica check (manual, Matt)**

The spec asks for the transform's output for a sample newsletter to be rendered through the Current reader replica before deploying. That replica and the sample newsletters live outside this repo and are not available to subagents. Produce the input for it:

```bash
uv run python -c "import sys; from app.services.feed_html import flatten_layout_tables; sys.stdout.write(flatten_layout_tables(sys.stdin.read()))" < SAMPLE.html > flattened.html
```

Report to Matt that this check is pending and is his to run; do not claim it was done. Do not merge into `deploy/prod`, build images, or run any `docker`/`compose` command as part of this plan — rollout (spec § Rollout) is a separate, user-driven step.
