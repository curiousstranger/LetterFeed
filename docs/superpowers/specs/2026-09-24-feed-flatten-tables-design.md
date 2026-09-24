# Flatten layout tables in feed content: design

Date: 2026-09-24
Branch: `feat/feed-flatten-tables` (off `origin/deploy/prod` @ 242450d)
Worktree: `.worktrees/feed-flatten-tables` (relative to the LetterFeed checkout)

This file is published with the fork, so it holds no deployment specifics.

**Fork-only.** This exists for one reading setup (FreshRSS feeding the Current
reader app). It will never be proposed upstream, which is why it is based on
`deploy/prod` rather than `upstream/master`: its migration must follow
`a3f1c2d4e5b6` (the OPML key), which upstream does not have. A migration based
on upstream's `75ed3dbf1e16` would give Alembic two heads once merged into
`deploy/prod`, and `alembic upgrade head` would fail at container start.

## Problem

In Current's default article view, LetterFeed newsletters render as stacks of
nested bordered boxes, with images shrunk to thumbnails. Current's own browser
view of the same entry page looks fine.

Root cause, established 2026-09-24:

1. HTML email is laid out with nested tables and per-element inline `style`
   attributes. One sample issue has 42 tables and 286 `style` attributes; its
   entry page, served by LetterFeed, has all of them.
2. FreshRSS 1.30 sanitizes feed HTML with an attribute allowlist
   (`app/Models/SimplePieCustom.php`). `style` is not on it, and
   `rename_attributes(['id', 'class'])` turns every `class` into
   `data-sanitized-class`. The copy Current stores has 42 tables, 0 `style`,
   0 `class`, 82 `data-sanitized-class`. This is hard-coded, not configurable.
3. Current renders LetterFeed articles from the feed body (`method=feed` in its
   diagnostic log for every LetterFeed article), not from the entry page.
4. Current's reader CSS treats every `<table>` as a data table: each is wrapped
   in a `.table-wrapper` with a 1px border, 8px radius and 2em margin, and
   every cell gets `0.7em 1em` padding. Six or seven levels of layout tables
   become six or seven nested frames, each narrowing the column. Photos render
   around 133-155px wide on a 375px screen.

A replica of Current's reader page (its CSS and JS, extracted from the app
binary) reproduces the screenshot box for box. Converting layout tables to
`<div>`s in the replica removes the frames and restores full-width images.

Styles cannot be carried through FreshRSS, so the fix has to be structural:
serve feed content whose layout does not depend on tables.

## Goals

- Feed `<content>` has newsletter layout tables flattened to `<div>`s, while
  genuine data tables stay tables.
- The flattening is paid once per entry, not on every feed fetch. Feeds are
  rebuilt from the database on every request, a newsletter's feed carries its
  whole history, and flattening costs about 16 ms per 100 KB email.
- A backend-only switch turns it off, e.g. if FreshRSS is dropped for a reader
  that honours inline styles.
- The stored original body, the `/entries/{id}` page and the API/UI entry views
  are unchanged.

## Non-goals

- Ad or sponsor images. Their shapes vary too much to design for; they render
  full width like any other image.
- Anything specific to one publisher.
- Refreshing articles that Current has already synced. Current is not expected
  to refetch them, so existing articles likely keep their frames.
- A UI control for the switch.

## Design

### Data

`entries.feed_body`: nullable `Text`, added by an Alembic migration with
`down_revision = "a3f1c2d4e5b6"`. Null means "no flattened copy yet".
Downgrade drops the column.

### Transform: `app/services/feed_html.py`

`flatten_layout_tables(html: str) -> str` is a pure function: no database and
no settings access.

Parse with BeautifulSoup's `html.parser` (already a dependency). Return a
fragment, with no `<html>`/`<body>` added. An empty or whitespace-only input is
returned unchanged.

**Layout-table rules.** Each table is judged on its own contents. The rules
are checked in order, and the first match makes the table a layout table:

1. `role` is `presentation` or `none`.
2. It contains another `<table>`.
3. It has fewer than 2 rows (its own `<tr>`s, not those of nested tables).
4. No row has 2 or more cells (`<td>`/`<th>` children of its own rows).
5. It has no `<th>`, and at least one of its own cells contains an `img`,
   `div`, `p`, `h1`-`h6`, `ul`, `ol`, `blockquote` or `table`.

Any other table is a data table and stays as it is. A data table nested inside
a layout table therefore survives.

Measured against 501 LetterFeed articles (20,391 tables) in Current's
database, rules 1-5 matched 16,834 / 980 / 2,092 / 326 / 146 tables and kept 13
as tables. One kept table is a genuine market-data table, correctly kept. The
other 12 are small "paid subscribers get" promo boxes that keep a frame. That
is accepted.

**Converting a layout table:**

- `<tbody>`, `<thead>`, `<tfoot>` belonging to it are unwrapped.
- The `<table>` and its own `<tr>`, `<td>` and `<th>` elements are renamed to
  `<div>`.
- Removed from those converted elements: `align`, `valign`, `width`, `height`,
  `bgcolor`, `background`, `cellpadding`, `cellspacing`, `border`, `colspan`,
  `rowspan`. `style`, `class`, `id` and everything else are kept.

"Own" matters: conversion must not reach into a nested data table. Classify
every table against the unmodified tree first, then convert the layout tables.

**Tracking pixels.** Anywhere in the document, remove any `<img>` whose
`width` or `height` attribute parses to an integer of 2 or less. Current hides
images under 20px anyway, but only after showing a 100px placeholder while
they load.

**Failure.** The function never raises. On any exception it logs a warning,
with the traceback, and returns the input unchanged. Callers do not need to
handle failure.

### Ingestion

`create_entry` (`app/crud/entries.py`) sets
`feed_body = flatten_layout_tables(body)` for every new entry, whether the
switch is on or off, so switching later takes effect immediately in either
direction. This covers both raw email bodies and extract-content bodies; the
latter has no tables and passes through unchanged.

### Serving

`_add_entries_to_feed` (`app/services/feed_generator.py`) emits
`entry.feed_body` when `settings.flatten_feed_tables` is true and
`entry.feed_body` is not null, and `entry.body` otherwise. The same rule
applies to the per-newsletter and master feeds.

### Switch

`flatten_feed_tables: bool = True` in `Settings` (`app/core/config.py`), read
from `LETTERFEED_FLATTEN_FEED_TABLES` through the existing `LETTERFEED_`
prefix. It is read only when feeds are rendered.

### Backfill

`backfill_feed_bodies()` runs once at startup as an APScheduler `date` job
(`id="feed_body_backfill"`), registered next to `initial_email_check` in
`app/core/scheduler.py`. It:

- selects entries with `feed_body IS NULL`, 50 at a time;
- fills each with `flatten_layout_tables(entry.body or "")`;
- commits after each batch, so the SQLite write lock stays short while the
  email job may be running in parallel;
- logs one line at start and one at the end, with counts.

It runs whether or not the switch is on. Since the transform never raises, an
entry it cannot flatten gets a copy of its body and is never retried. Only
entries that existed before this change are ever null, because new ones are
filled at ingestion.

## Testing

Test-first; each test is watched failing before its code is written.

- `flatten_layout_tables`:
  - each of rules 1-5 triggers conversion;
  - a data table (header row plus rows of text) is kept;
  - a data table nested in a layout table is kept while its parent is flattened;
  - attribute removal on converted elements, and `style`/`class` kept;
  - tracking-pixel removal, and larger images kept;
  - HTML with no tables comes back equivalent;
  - an empty body;
  - malformed HTML does not raise;
  - an exception inside the transform returns the input.
- `create_entry` fills `feed_body`.
- Feed output, per-newsletter and master:
  - switch on serves `feed_body`;
  - switch off serves `body`;
  - switch on with a null `feed_body` serves `body`.
- `backfill_feed_bodies`:
  - fills null rows across more than one batch;
  - leaves filled rows alone;
  - completes when the transform fails for an entry.
- Fixtures are small hand-written HTML with the table structures of the
  observed newsletters (Mailchimp-style nesting, `role="presentation"` tables,
  a market-data table). They contain no real newsletter content.

Before deploying, render the transform's output for a sample newsletter through
the Current reader replica and check that it has no nested frames.

## Rollout

1. Merge `feat/feed-flatten-tables` into `deploy/prod` and push.
2. Rebuild the backend image only. There is no frontend change.
3. Start it; the migration adds the column and the backfill fills it.
4. Expected effects:
   - FreshRSS sees changed content for existing entries and updates its stored
     copies. With `mark_updated_article_unread = false` they are not re-marked
     unread.
   - Current probably keeps its existing copies. **New mail is the real test.**

Rollback:

- **Preferred:** set `LETTERFEED_FLATTEN_FEED_TABLES=false` and restart. Feeds
  serve the original bodies at once, and the column stays in place.
- **Previous image:** do not simply re-tag it. The backend container runs
  `alembic upgrade head` before starting uvicorn (`backend/Dockerfile`), and
  an older image does not know this revision, so it would fail to start. First
  run `alembic downgrade a3f1c2d4e5b6` with the new image against the data
  volume, as a one-off container rather than an exec. Then re-tag the older
  image.
