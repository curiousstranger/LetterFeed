# Per-entry links in feeds: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Atom entry LetterFeed emits carries `<link rel="alternate" href="<APP_BASE_URL>/api/entries/<id>"/>`, and that URL serves the stored entry body as a sandboxed standalone page. Then the fork deploys it from source, through a `deploy/prod` integration branch.

**Architecture:** A new public FastAPI router, `GET /entries/{entry_id}`, returns `entry.body` verbatim with a strict CSP sandbox and other safety headers. It uses a new `get_entry` CRUD lookup. `_add_entries_to_feed` adds the link through a `_entry_url` helper, so the per-newsletter and master feeds both get it. Deployment moves from a COPY overlay to a buildx build of `backend/` from a clean `deploy/prod` worktree, run natively on the deployment host's daemon.

**Tech Stack:** Python 3.13, FastAPI/Starlette, SQLAlchemy 2.0, feedgen, pytest, ruff, uv. Docker with buildx, compose, FreshRSS (PHP/SQLite).

**Spec:** `docs/superpowers/specs/2026-09-21-entry-links-design.md` (on this branch). Read it before starting any task. This plan argues from it.

## Global Constraints

- **The fork is public.** Nothing committed or pushed may contain deployment specifics: IPs, hostnames, usernames, container names, hardware, or local absolute paths. That covers code, this plan, deploy docs, commit messages and PR text. Refer to deployment values only by the variable names `LETTERFEED_URL`, `DOCKER_CONTEXT`, `DOCKER_API_VERSION`, `FEED_HOST_DIR`, `FRESHRSS_CONTAINER` and `FRESHRSS_USER`. Real values go only in the git-ignored `deploy/.env`. Their sources are the local, git-excluded `CLAUDE.md` in the main LetterFeed checkout, plus the user. Before every push, run `git log -p <base>..HEAD` and grep it for specifics (Task 5 gives the exact command).
- **`$LF`** in this plan means the absolute path of the main LetterFeed checkout. It's written as a variable because this file is pushed. The session prompt gives the real path. Expand it in every command you run and in every subagent dispatch, and never write the expanded path into a committed file.
- **Working directories.** Tasks 1–5 run in the worktree `$LF/.worktrees/entry-links` (branch `feat/entry-links`). Tasks 7–11 run in `$LF/.worktrees/deploy-prod` (branch `deploy/prod`, created in Task 7). Every subagent dispatch must state the absolute working directory **and** tell the agent to `cd` there before its first write. Never modify the main checkout at `$LF`, except the legacy `deploy/` retirement in Task 11, and only with the user's OK.
- **Backend commands** run from `backend/` via uv: `uv sync --group test`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check app`. Never bare `python3` or `pytest`.
- **TDD.** Watch every test fail on unmodified code before writing the implementation (superpowers:test-driven-development). Header tests compare against **literal strings written in the test**, never the module constant.
- **Evidence.** Any claim that tests, lint or a check passed must paste the actual command and its full output. Treat subagent pass claims as unverified until the output has been seen.
- **ruff `D` rules are on.** Every new function, including test functions, needs a one-line imperative docstring.
- **Git.** Never commit to or push `master`. Never open an upstream PR, issue or comment. `feat/entry-links` goes to a PR against `curiousstranger/LetterFeed` `master`. `deploy/prod` is pushed to `origin` but never PR'd. An eventual upstream branch (not part of this plan) says "Closes #19" and drops the spec and plan.
- **Deployment host.** Pass `--context "$DOCKER_CONTEXT"` on every docker command. Source `deploy/.env` only in a subshell or a single command, never into a persistent shell: the CLI reads `DOCKER_CONTEXT` and `DOCKER_API_VERSION` from the environment itself. Never SSH. Remote calls take about 8 seconds, so don't loop them.
- **feed-host.** Never edit it; hand the user the `image:` line change instead. Run compose only against `$FEED_HOST_DIR`, only after the `config --services` check, and do a `--dry-run` before every `up`. Never read or print feed-host's `.env`, and never run bare `docker compose config` there.
- **Tags.** `letterfeed-backend:fork` (moving) and `letterfeed-backend:fork-<sha>` (immutable). Keep `letterfeed-backend:fix-100` on the host as the rollback image.
- **User gates** (stop and ask; don't proceed on your own): `brew install docker-buildx` (Task 6); the `image:` edit in feed-host (Task 9); FreshRSS `mark_updated_article_unread` being on (Task 10); any FreshRSS backfill apply (Task 10: the user runs it); deleting the legacy `deploy/` directory (Task 11).

---

## File structure

`feat/entry-links` (Tasks 1–5):

| File | Change | Responsibility |
|---|---|---|
| `backend/app/crud/entries.py` | modify | add `get_entry(db, entry_id)`, a primary-key lookup |
| `backend/app/routers/entries.py` | create | `GET /entries/{entry_id}`, the safety header constant, and the no-state-changing-GET invariant comment |
| `backend/app/main.py` | modify | register `entries.router` without auth |
| `backend/app/services/feed_generator.py` | modify | `_entry_url()` helper; `fe.link(...)` in `_add_entries_to_feed` |
| `backend/app/tests/test_crud.py` | modify | `get_entry` tests |
| `backend/app/tests/test_routers.py` | modify | endpoint tests (body, content type, exact headers, 404, public under auth) |
| `backend/app/tests/services/test_feed_generator.py` | modify | per-entry link tests for both feeds, plus the trailing-slash case |

`deploy/prod` (Tasks 7–11):

| File | Change | Responsibility |
|---|---|---|
| `deploy/README.md` | create (`git add -f`) | generic runbook: buildx, branch, build, tags, switch, rollback, checks |
| `deploy/.env.example` | create (`git add -f`) | placeholder values for the six variables |
| `deploy/.env` | create, **never committed** | real values |

---

### Task 1: `get_entry` CRUD lookup

**Working directory:** `$LF/.worktrees/entry-links`. `cd` there before the first write. Run commands from `backend/`.

**Files:**
- Modify: `backend/app/crud/entries.py` (add after `get_entry_by_message_id`)
- Test: `backend/app/tests/test_crud.py`

**Interfaces:**
- Consumes: `create_entry(db, EntryCreate, newsletter_id) -> Entry`, `create_newsletter(db, NewsletterCreate)` (existing).
- Produces: `get_entry(db: Session, entry_id: str) -> Entry | None`, used by Task 2.

- [ ] **Step 1: Write the failing tests.** In `backend/app/tests/test_crud.py`, change the import line
  `from app.crud.entries import create_entry, get_all_entries, get_entries_by_newsletter`
  to
  ```python
  from app.crud.entries import (
      create_entry,
      get_all_entries,
      get_entries_by_newsletter,
      get_entry,
  )
  ```
  and append:
  ```python
  def test_get_entry(db_session: Session):
      """Test getting a single entry by its id."""
      newsletter = create_newsletter(
          db_session,
          NewsletterCreate(
              name="Get Entry Newsletter",
              sender_emails=[f"sender_{uuid.uuid4()}@test.com"],
          ),
      )
      created = create_entry(
          db_session,
          EntryCreate(
              subject="Get Me",
              body="<p>Body</p>",
              message_id=f"<{uuid.uuid4()}@test.com>",
          ),
          newsletter.id,
      )

      entry = get_entry(db_session, created.id)

      assert entry is not None
      assert entry.id == created.id
      assert entry.subject == "Get Me"


  def test_get_entry_unknown_id(db_session: Session):
      """Test that getting an unknown entry id returns None."""
      assert get_entry(db_session, "does-not-exist") is None
  ```

- [ ] **Step 2: Run to verify they fail.**
  Run: `uv sync --group test && uv run pytest app/tests/test_crud.py -k get_entry -v`
  Expected: collection error, `ImportError: cannot import name 'get_entry'`. Paste the output.

- [ ] **Step 3: Implement.** In `backend/app/crud/entries.py`, after `get_entry_by_message_id`:
  ```python
  def get_entry(db: Session, entry_id: str):
      """Retrieve an entry by its id."""
      logger.debug(f"Querying for entry with id={entry_id}")
      return db.query(Entry).filter(Entry.id == entry_id).first()
  ```

- [ ] **Step 4: Run to verify they pass.**
  Run: `uv run pytest app/tests/test_crud.py -v`
  Expected: all pass, including `test_get_entry` and `test_get_entry_unknown_id`. Paste the output.

- [ ] **Step 5: Commit.**
  ```bash
  git add backend/app/crud/entries.py backend/app/tests/test_crud.py
  git commit -m "feat: add get_entry lookup by id" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  ```

---

### Task 2: Public, sandboxed `GET /entries/{entry_id}`

**Working directory:** `$LF/.worktrees/entry-links`. `cd` there before the first write. Run commands from `backend/`.

**Files:**
- Create: `backend/app/routers/entries.py`
- Modify: `backend/app/main.py` (import and `include_router`)
- Test: `backend/app/tests/test_routers.py`

**Interfaces:**
- Consumes: `get_entry(db, entry_id) -> Entry | None` (Task 1); `get_db` from `app.core.database`.
- Produces: the route `GET /entries/{entry_id}`, published by the frontend as `<APP_BASE_URL>/api/entries/{entry_id}` (Task 3 links to it). Module constant `SAFETY_HEADERS: dict[str, str]` (tests must **not** import it).

- [ ] **Step 1: Write the failing tests.** Append to `backend/app/tests/test_routers.py`. The header values are written out literally on purpose: browsers silently ignore a malformed directive, so a typo would fail open, and exact matching makes any policy change visible in review.
  ```python
  EXPECTED_ENTRY_CSP = (
      "sandbox allow-popups allow-popups-to-escape-sandbox; "
      "default-src 'none'; img-src * data:; style-src * 'unsafe-inline'; "
      "font-src * data:; media-src *; form-action 'none'; base-uri 'none'; "
      "frame-ancestors 'none'"
  )


  def _create_entry_via_api(client: TestClient, body: str) -> str:
      """Create a newsletter with one entry through the API and return the entry id."""
      newsletter = client.post(
          "/newsletters",
          json={
              "name": "Entry Page Newsletter",
              "sender_emails": [f"entry_page_{uuid.uuid4()}@example.com"],
          },
      ).json()
      entry = client.post(
          f"/newsletters/{newsletter['id']}/entries",
          json={
              "subject": "Entry Page",
              "body": body,
              "message_id": f"<entry_page_{uuid.uuid4()}@test.com>",
          },
      ).json()
      return entry["id"]


  def test_get_entry_page_returns_stored_body(client: TestClient):
      """Test that the entry page returns the exact stored body as HTML."""
      body = '<html><body><h1>Héllo ✉</h1><script>alert(1)</script></body></html>'
      entry_id = _create_entry_via_api(client, body)

      response = client.get(f"/entries/{entry_id}")

      assert response.status_code == 200
      assert response.headers["content-type"] == "text/html; charset=utf-8"
      assert response.text == body


  def test_get_entry_page_sends_safety_headers(client: TestClient):
      """Test that the entry page sends the exact sandbox and safety headers."""
      entry_id = _create_entry_via_api(client, "<p>hi</p>")

      response = client.get(f"/entries/{entry_id}")

      assert response.status_code == 200
      assert response.headers["content-security-policy"] == EXPECTED_ENTRY_CSP
      assert response.headers["x-content-type-options"] == "nosniff"
      assert response.headers["referrer-policy"] == "no-referrer"


  def test_get_entry_page_unknown_id(client: TestClient):
      """Test that an unknown entry id returns 404."""
      response = client.get("/entries/does-not-exist")
      assert response.status_code == 404
      assert response.json() == {"detail": "Entry not found"}


  def test_get_entry_page_is_public_when_auth_enabled(
      client: TestClient, db_session: Session
  ):
      """Test that the entry page needs no token even when auth is configured."""
      entry_id = _create_entry_via_api(client, "<p>public</p>")
      create_or_update_settings(
          db_session,
          SettingsCreate(
              imap_server="test.com",
              imap_username="test",
              imap_password="password",
              auth_username="admin",
              auth_password="password",
          ),
      )
      # Sanity check: auth really is on for protected routes.
      assert client.get("/newsletters").status_code == 401

      response = client.get(f"/entries/{entry_id}")

      assert response.status_code == 200
      assert response.text == "<p>public</p>"
  ```
  (`uuid`, `TestClient`, `Session`, `create_or_update_settings` and `SettingsCreate` are already imported at the top of this file.)

- [ ] **Step 2: Run to verify they fail.**
  Run: `uv run pytest app/tests/test_routers.py -k entry_page -v`
  Expected: `test_get_entry_page_returns_stored_body`, `..._sends_safety_headers` and `..._is_public_when_auth_enabled` fail with `assert 404 == 200`. `test_get_entry_page_unknown_id` fails because the body is `{"detail": "Not Found"}`, not `{"detail": "Entry not found"}`. Paste the output. If any test passes here, stop: it isn't testing the new behavior.

- [ ] **Step 3: Create `backend/app/routers/entries.py`.**
  ```python
  from fastapi import APIRouter, Depends, HTTPException
  from fastapi.responses import Response
  from sqlalchemy.orm import Session

  from app.core.database import get_db
  from app.core.logging import get_logger
  from app.crud.entries import get_entry

  logger = get_logger(__name__)
  router = APIRouter()

  # The entry body is untrusted, sender-controlled HTML served on the same
  # origin as the UI and API. The CSP sandbox (no allow-scripts, no
  # allow-same-origin) disables JS and gives the page an opaque origin, so it
  # can't read the UI's localStorage token or make credentialed requests. Forms,
  # framing and <base> are blocked; images, styles, fonts and media may load so
  # newsletter layouts still render.
  #
  # INVARIANT: LetterFeed must never add a state-changing GET route. The sandbox
  # does not stop same-origin subresource requests: <img src="/api/..."> in an
  # entry still sends a GET.
  SAFETY_HEADERS = {
      "Content-Security-Policy": (
          "sandbox allow-popups allow-popups-to-escape-sandbox; "
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
  ```
  Log the entry id only, never the body.

- [ ] **Step 4: Register the router without auth.** In `backend/app/main.py`, change
  `from app.routers import auth, feeds, health, imap, newsletters`
  to
  `from app.routers import auth, entries, feeds, health, imap, newsletters`
  and after `app.include_router(feeds.router)` add:
  ```python
  app.include_router(entries.router)
  ```

- [ ] **Step 5: Run to verify they pass.**
  Run: `uv run pytest app/tests/test_routers.py -v`
  Expected: all pass, including the four `entry_page` tests. Paste the output.

- [ ] **Step 6: Commit.**
  ```bash
  git add backend/app/routers/entries.py backend/app/main.py backend/app/tests/test_routers.py
  git commit -m "feat: serve entry bodies at a sandboxed public /entries/{id} page" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  ```

---

### Task 3: Per-entry `<link rel="alternate">` in both feeds

**Working directory:** `$LF/.worktrees/entry-links`. `cd` there before the first write. Run commands from `backend/`.

**Files:**
- Modify: `backend/app/services/feed_generator.py` (new helper above `_add_entries_to_feed`; one line inside its loop)
- Test: `backend/app/tests/services/test_feed_generator.py`

**Interfaces:**
- Consumes: the route path `/entries/{id}`, published as `/api/entries/{id}` (Task 2); `settings.app_base_url`.
- Produces: `_entry_url(entry_id: str) -> str`.

`settings` is a frozen pydantic model, so tests can't assign to it. They swap the module's `settings` for `settings.model_copy(update=...)`. Don't patch it with a `MagicMock` in these tests: `master_feed_limit` would become a mock and break the SQL `LIMIT`.

- [ ] **Step 1: Write the failing tests.** Append to `backend/app/tests/services/test_feed_generator.py` and add the new imports at the top (keep ruff's isort order: stdlib, third-party, first-party):
  ```python
  import uuid
  import xml.etree.ElementTree as ET

  from sqlalchemy.orm import Session

  from app.core.config import settings
  from app.crud.entries import create_entry
  from app.crud.newsletters import create_newsletter
  from app.schemas.entries import EntryCreate
  from app.schemas.newsletters import NewsletterCreate
  from app.services import feed_generator
  from app.services.feed_generator import generate_feed
  ```
  (Merge with the existing `from app.services.feed_generator import generate_master_feed` into one import line. `patch` is already imported.)
  ```python
  ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


  def _seed_newsletter_with_entries(db: Session, count: int = 2):
      """Create a newsletter with `count` entries and return (newsletter, entry ids)."""
      newsletter = create_newsletter(
          db,
          NewsletterCreate(
              name="Link Test Newsletter",
              sender_emails=[f"links_{uuid.uuid4()}@example.com"],
          ),
      )
      ids = [
          create_entry(
              db,
              EntryCreate(
                  subject=f"Entry {i}",
                  body=f"<p>Body {i}</p>",
                  message_id=f"<links_{uuid.uuid4()}@test.com>",
              ),
              newsletter.id,
          ).id
          for i in range(count)
      ]
      return newsletter, ids


  def _entry_links_by_id(feed_xml: bytes) -> dict[str, list[dict[str, str]]]:
      """Map each Atom entry's LetterFeed id to the attributes of its <link> elements."""
      root = ET.fromstring(feed_xml)
      result = {}
      for entry in root.findall("atom:entry", ATOM_NS):
          urn = entry.find("atom:id", ATOM_NS).text
          entry_id = urn.removeprefix("urn:letterfeed:entry:")
          result[entry_id] = [
              dict(link.attrib) for link in entry.findall("atom:link", ATOM_NS)
          ]
      return result


  def _patched_base_url(base_url: str):
      """Patch the feed generator's settings with a different app_base_url."""
      return patch.object(
          feed_generator,
          "settings",
          settings.model_copy(update={"app_base_url": base_url}),
      )


  def test_generate_feed_entries_link_to_entry_page(db_session: Session):
      """Test that each newsletter feed entry links to its /api/entries page."""
      newsletter, ids = _seed_newsletter_with_entries(db_session)

      with _patched_base_url("https://lf.example.test"):
          links = _entry_links_by_id(generate_feed(db_session, newsletter.id))

      assert sorted(links) == sorted(ids)
      for entry_id, entry_links in links.items():
          assert entry_links == [
              {
                  "href": f"https://lf.example.test/api/entries/{entry_id}",
                  "rel": "alternate",
              }
          ]


  def test_generate_master_feed_entries_link_to_entry_page(db_session: Session):
      """Test that each master feed entry links to its /api/entries page."""
      _, ids = _seed_newsletter_with_entries(db_session)

      with _patched_base_url("https://lf.example.test"):
          links = _entry_links_by_id(generate_master_feed(db_session))

      assert sorted(links) == sorted(ids)
      for entry_id, entry_links in links.items():
          assert entry_links == [
              {
                  "href": f"https://lf.example.test/api/entries/{entry_id}",
                  "rel": "alternate",
              }
          ]


  def test_entry_link_with_trailing_slash_base_url(db_session: Session):
      """Test that a trailing slash on app_base_url doesn't produce //api."""
      newsletter, ids = _seed_newsletter_with_entries(db_session, count=1)

      with _patched_base_url("https://lf.example.test/"):
          links = _entry_links_by_id(generate_feed(db_session, newsletter.id))

      assert links[ids[0]][0]["href"] == (
          f"https://lf.example.test/api/entries/{ids[0]}"
      )
  ```

- [ ] **Step 2: Run to verify they fail.**
  Run: `uv run pytest app/tests/services/test_feed_generator.py -v`
  Expected: the three new tests fail because `entry_links == []` (feedgen emits no entry `<link>` today). The trailing-slash test fails with `IndexError: list index out of range`. The existing `test_generate_master_feed_respects_limit` still passes. Paste the output.

- [ ] **Step 3: Implement.** In `backend/app/services/feed_generator.py`, add above `_add_entries_to_feed`:
  ```python
  def _entry_url(entry_id: str) -> str:
      """Return the public URL of an entry's standalone page."""
      # APP_BASE_URL is the frontend's URL. The frontend exposes the backend
      # under /api (see frontend/src/middleware.ts), so the backend route
      # /entries/{id} is published at <APP_BASE_URL>/api/entries/{id}.
      return f"{settings.app_base_url.rstrip('/')}/api/entries/{entry_id}"
  ```
  and in `_add_entries_to_feed`, directly after `fe.content(entry.body, type="html")`:
  ```python
          fe.link(href=_entry_url(entry.id), rel="alternate")
  ```
  Leave the Atom `<id>` (`urn:letterfeed:entry:<id>`) unchanged: changing it would make readers treat every entry as new.

- [ ] **Step 4: Run to verify they pass.**
  Run: `uv run pytest app/tests/services/test_feed_generator.py app/tests/test_routers.py -v`
  Expected: all pass, including the existing `test_get_newsletter_feed`. Paste the output.

- [ ] **Step 5: Commit.**
  ```bash
  git add backend/app/services/feed_generator.py backend/app/tests/services/test_feed_generator.py
  git commit -m "feat: link each feed entry to its standalone page" -m "Refs #19" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  ```
  (Write "Refs #19", not "Closes #19": in the fork, "#19" would point at the fork's own issue numbers. The upstream PR description carries "Closes #19".)

---

### Task 4: Gauntlet and adversarial browser check

**Working directory:** `$LF/.worktrees/entry-links`. `cd` there before any write. This task runs the browser pane, so the controller runs it, not a subagent.

**Files:** none committed. The fixture lives in a temp dir: `ADV="${TMPDIR:-/tmp}/letterfeed-adv"`. Shell state doesn't persist between Bash calls, so re-derive `ADV` in each command.

- [ ] **Step 1: Full gauntlet.** From `backend/`, run each command and paste its full output:
  ```bash
  uv sync --group test
  ```
  ```bash
  uv run pytest
  ```
  ```bash
  uv run ruff check .
  ```
  ```bash
  uv run ruff format --check app
  ```
  Expected: every test passes; `All checks passed!`; `N files already formatted`. If format fails, run `uv run ruff format app`, rerun the tests, and commit as `style: ruff format`.

- [ ] **Step 2: Write the fixture.** Every vector that executes requests a unique `/canary/<vector>` path. JS payloads use `new Image().src`, not `fetch`: `connect-src` falls back to `default-src 'none'` and would block `fetch` even if JS ran, which would hide a failure.
  ```bash
  ADV="${TMPDIR:-/tmp}/letterfeed-adv"; mkdir -p "$ADV" && cat > "$ADV/fixture.html" <<'EOF'
  <!doctype html>
  <html><head>
  <meta http-equiv="refresh" content="0;url=javascript:void(new Image().src='/canary/meta-refresh')">
  <base href="/canary/base/">
  <title>LetterFeed sandbox check</title>
  </head><body>
  <h1>LetterFeed sandbox check</h1>
  <script>new Image().src='/canary/inline-script'</script>
  <img src="x" onerror="new Image().src='/canary/img-onerror'">
  <p><a id="js" href="javascript:void(new Image().src='/canary/js-link')">javascript: link</a></p>
  <p><a id="js-blank" href="javascript:void(new Image().src='/canary/js-link-blank')" target="_blank">javascript: link, new tab</a></p>
  <form action="/canary/form" method="post"><input name="q" value="1"><button id="submit" type="submit">Submit form</button></form>
  <iframe src="/canary/iframe"></iframe>
  <object data="/canary/object"></object>
  <embed src="/canary/embed">
  <img src="relative.png" alt="base check">
  <img src="/canary/control" alt="control">
  <p><a id="ok-blank" href="/health" target="_blank">ordinary new-tab link</a></p>
  </body></html>
  EOF
  ```
  If `<base>` were honored, `relative.png` and `x` would resolve under `/canary/base/`. Blocked, they resolve to `/entries/relative.png` and `/entries/x`, which aren't canaries.

- [ ] **Step 3: Start the branch's backend** with a throwaway DB, as a background command, logging to a file. The access log goes to stdout (`app/core/logging.py`):
  ```bash
  ADV="${TMPDIR:-/tmp}/letterfeed-adv"; cd $LF/.worktrees/entry-links/backend && rm -f "$ADV/adv.db" && LETTERFEED_DATABASE_URL="sqlite:///$ADV/adv.db" LETTERFEED_SECRET_KEY=adv-check uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 > "$ADV/server.log" 2>&1
  ```
  (Use Bash `run_in_background: true`.) Then check `curl -s http://127.0.0.1:8765/health` returns a healthy JSON body. IMAP errors from the scheduler in the log are expected, since no IMAP is configured.

- [ ] **Step 4: Seed one newsletter and one entry through the API**, and print the entry URL:
  ```bash
  ADV="${TMPDIR:-/tmp}/letterfeed-adv"; cd $LF/.worktrees/entry-links/backend && ADV="$ADV" uv run python - <<'EOF'
  import json, os, urllib.request

  base = "http://127.0.0.1:8765"
  adv = os.environ["ADV"]

  def post(path, payload):
      req = urllib.request.Request(
          base + path,
          data=json.dumps(payload).encode(),
          headers={"Content-Type": "application/json"},
          method="POST",
      )
      with urllib.request.urlopen(req) as r:
          return json.load(r)

  nl = post("/newsletters", {"name": "Sandbox check", "sender_emails": ["sandbox@example.com"]})
  body = open(f"{adv}/fixture.html").read()
  entry = post(f"/newsletters/{nl['id']}/entries",
               {"subject": "Sandbox check", "body": body, "message_id": "<sandbox@example.com>"})
  print(f"{base}/entries/{entry['id']}")
  EOF
  ```
  Also confirm the feed links to it: `curl -s http://127.0.0.1:8765/feeds/all | grep -o 'href="[^"]*/api/entries/[^"]*"'`. Locally, `APP_BASE_URL` defaults to `http://backend:8000`, so the href is `http://backend:8000/api/entries/<id>`. That's expected.

- [ ] **Step 5: Open the entry in the browser pane.** `mcp__Claude_Browser__preview_start` with `url` = the printed entry URL. Take a screenshot: the heading and the control image placeholder render. Then click, in order: `#js`, `#js-blank`, `#submit`, `#ok-blank`. Use `find`/`read_page` refs. After `#ok-blank`, call `tabs_context` and confirm a new tab opened on `/health`. Close any extra tabs afterwards.

- [ ] **Step 6: Judge from the access log.**
  ```bash
  ADV="${TMPDIR:-/tmp}/letterfeed-adv"; grep -E '"(GET|POST) /(canary|health|entries)' "$ADV/server.log"
  ```
  **Pass** only if `/canary/control` appears, **no other** `/canary/` path appears, and `GET /health` appears (from the new tab). Any other canary is a failure: stop, don't open the PR, and report which vector fired. Save the excerpt for the PR description.

- [ ] **Step 7: Stop the server** (kill the background task) and keep `$ADV/fixture.html` for the PR.

---

### Task 5: Push `feat/entry-links` and open the fork PR

**Working directory:** `$LF/.worktrees/entry-links`.

- [ ] **Step 1: Public-content gate.** Review the full diff and grep it for deployment specifics:
  ```bash
  git log -p upstream/master..HEAD | grep -niE '([0-9]{1,3}\.){3}[0-9]{1,3}|/Users/|/home/|~/|\.local\b|\.lan\b|container_name|ssh ' || echo "no hits"
  ```
  Also grep for every **value** in the git-excluded `CLAUDE.md` deployment section: the docker context name, API version, checkout path, hostnames, usernames. Check each one without printing the values into anything committed. Expected hits: `127.0.0.1` in this plan's Task 4 (loopback, generic), plus generic mentions that are already in the spec (for example "feed-host" as the stack's name, if the user accepts that; otherwise stop and ask). Show the user any hit that isn't obviously generic before pushing.

- [ ] **Step 2: Push.**
  ```bash
  git push -u origin feat/entry-links
  ```

- [ ] **Step 3: Open the PR against the fork** (never upstream). Write the body to a temp file and pass it with `--body-file`. The body contains: summary; "Implements LeonMusCoden/LetterFeed#19 (fork PR; upstream PR later, which drops the spec and plan)"; that the customizable template idea from #19 isn't included; the Security model summary from the spec, including the **no state-changing GET** invariant and the "a link is the whole email" caveat; the gauntlet output from Task 4 Step 1; the adversarial log excerpt and the fixture HTML (in a collapsed `<details>` block) from Task 4; and the footer line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
  ```bash
  gh pr create --repo curiousstranger/LetterFeed --base master --head feat/entry-links \
    --title "feat: per-entry links to a sandboxed entry page" --body-file "${TMPDIR:-/tmp}/letterfeed-adv/pr-body.md"
  ```
  Grep the body file for specifics (same pattern as Step 1) before running this.

- [ ] **Step 4:** Use the ccd_pr tools to read CI status; don't poll `gh`. Report the PR URL.

---

### Task 6: Install buildx on the Mac (user gate)

**Working directory:** any (this changes the Mac, not a repo).

- [ ] **Step 1: Check the current state.** Run `docker buildx version`. If it prints a version, skip to Step 4.
- [ ] **Step 2: Ask the user** for explicit OK to run `brew install docker-buildx`, or ask them to run it. Don't run it without a yes.
- [ ] **Step 3: Follow the formula's caveat.** `~/.docker/config.json` needs `"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]`. Read the file first and add the key only if it's missing, leaving everything else as is. This file can hold registry auth, so print only the `cliPluginsExtraDirs` key when checking it (for example `jq '.cliPluginsExtraDirs' ~/.docker/config.json`), never the whole file.
- [ ] **Step 4: Verify.** `docker buildx version` prints a version. Then, in one command: `(set -a; . $LF/.worktrees/deploy-prod/deploy/.env; set +a; docker --context "$DOCKER_CONTEXT" buildx ls)`. That needs Task 7's `deploy/.env`; if Task 7 hasn't run yet, do this check at the end of Task 7. Expect a builder for that context using the `docker` driver.

---

### Task 7: `deploy/prod` integration branch, worktree and deploy docs

**Working directory:** `$LF/.worktrees/deploy-prod` (created in Step 1; run Step 1 from the main checkout's git dir via `git -C`). `cd` into it before the first write.

**Files:**
- Create: `deploy/README.md`, `deploy/.env.example` (committed with `git add -f`)
- Create: `deploy/.env` (never committed)

- [ ] **Step 1: Create the branch and worktree** off `upstream/master`:
  ```bash
  git -C $LF fetch upstream
  git -C $LF worktree add $LF/.worktrees/deploy-prod -b deploy/prod upstream/master
  git -C $LF/.worktrees/deploy-prod branch --unset-upstream 2>/dev/null || true
  ```

- [ ] **Step 2: Merge the three branches** (they touch disjoint files, so no conflicts are expected; if one appears, stop and report it):
  ```bash
  cd $LF/.worktrees/deploy-prod
  git merge --no-ff fix/processor-sees-all-newsletters -m "Merge fix/processor-sees-all-newsletters into deploy/prod"
  git merge --no-ff fix/newsletters-endpoint-returns-all -m "Merge fix/newsletters-endpoint-returns-all into deploy/prod"
  git merge --no-ff feat/entry-links -m "Merge feat/entry-links into deploy/prod"
  ```
  Confirm the fix commits are included: `git merge-base --is-ancestor e84e1bb HEAD && git merge-base --is-ancestor 044fabc HEAD && echo ok`.

- [ ] **Step 3: Run the gauntlet on the merged tree.** From `backend/`: `uv sync --group test`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check app`. Paste the output. If mypy-style issues come up only from the fix branches' interaction, report them; don't fix them here.

- [ ] **Step 4: Write `deploy/.env.example`:**
  ```bash
  # Copy to deploy/.env (git-ignored) and fill in real values.
  # Source only in a subshell or a single command:
  #   (set -a; . deploy/.env; set +a; docker --context "$DOCKER_CONTEXT" ...)
  # The Docker CLI reads DOCKER_CONTEXT and DOCKER_API_VERSION itself, so a shell
  # that has sourced this file sends every docker command to the deployment host.

  # Public LetterFeed URL (its APP_BASE_URL, i.e. the frontend)
  LETTERFEED_URL=https://letterfeed.example.com
  # docker context for the deployment host
  DOCKER_CONTEXT=example-host
  # API version the host's daemon needs
  DOCKER_API_VERSION=1.45
  # feed-host checkout whose docker-compose.yml defines the LetterFeed services
  FEED_HOST_DIR=/path/to/feed-host
  # FreshRSS container name
  FRESHRSS_CONTAINER=freshrss
  # FreshRSS username (DB: /var/www/FreshRSS/data/users/$FRESHRSS_USER/db.sqlite)
  FRESHRSS_USER=example-user
  ```

- [ ] **Step 5: Write `deploy/README.md`** with exactly this content:
  ````markdown
  # Deploying the fork

  The fork's own deployment: the `feed-host` compose stack on a remote Docker
  host, running LetterFeed behind FreshRSS. This file is public, so it holds no
  deployment specifics. Every value is a variable from `deploy/.env` (git-ignored;
  see `deploy/.env.example`).

  ## Rules

  - Source `deploy/.env` only in a subshell or a single command. The Docker CLI
    reads `DOCKER_CONTEXT` and `DOCKER_API_VERSION` itself, so a shell that has
    sourced it sends every `docker` command to the deployment host.
  - Always pass `--context "$DOCKER_CONTEXT"`. Never SSH to the host.
  - Run compose only against `$FEED_HOST_DIR`, and first check that its compose
    file defines the LetterFeed services (below). From a checkout that lacks them,
    `down` or `--remove-orphans` destroys the LetterFeed containers.
  - feed-host has its own `.env` with live credentials. Never read or print it,
    and never run bare `docker compose config` in `$FEED_HOST_DIR`.
  - Don't point feed-host's `image:` at upstream's `:latest` while the fork
    carries fixes that upstream hasn't shipped.

  ## One-time setup: buildx

  Docker CLI 23+ sends `docker build` through the buildx plugin, which
  Homebrew's `docker` formula doesn't include.

  ```bash
  brew install docker-buildx
  # then follow its caveat: add
  #   "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]
  # to ~/.docker/config.json
  docker buildx version
  (set -a; . deploy/.env; set +a; docker --context "$DOCKER_CONTEXT" buildx ls)
  ```

  Builds against the host's context run natively on the host's daemon, so the
  image is built for the host's architecture, whatever the client machine is.

  ## The `deploy/prod` branch

  `deploy/prod` is `upstream/master` plus the fork's fix and feature branches,
  merged. It's pushed to `origin` so every built commit can be recovered, and it's
  never PR'd. Fix and feature branches stay small and upstream-shaped; only
  `deploy/prod` combines them.

  Update it by merging again, from its own worktree `.worktrees/deploy-prod`:

  ```bash
  git fetch upstream
  git merge upstream/master          # when upstream moves
  git merge --no-ff <branch>         # a new or updated fix/feature branch
  git push origin deploy/prod
  ```

  When a fix ships upstream, merging `upstream/master` makes its branch's merge
  a no-op.

  ## Build

  Build from the clean `deploy/prod` worktree. `backend/` has no `.dockerignore`,
  so a dev checkout would upload `.venv` as build context. Only `backend/` is
  sent, so `deploy/.env` never enters the image.

  ```bash
  (
    set -a; . deploy/.env; set +a
    sha=$(git rev-parse --short HEAD)
    docker --context "$DOCKER_CONTEXT" buildx build \
      -t letterfeed-backend:fork -t "letterfeed-backend:fork-$sha" \
      --label org.opencontainers.image.source=https://github.com/curiousstranger/LetterFeed \
      --label "org.opencontainers.image.revision=$sha" \
      backend
    docker --context "$DOCKER_CONTEXT" image inspect --format '{{.Id}}' "letterfeed-backend:fork-$sha"
  )
  ```

  The image must land in the host's image store (buildx's `docker` driver for
  that context). If `image inspect` can't find it, a different builder was
  selected; rerun with `--load`.

  ## Tags

  - `letterfeed-backend:fork` is the moving tag feed-host names, so a new deploy
    needs no compose edit.
  - `letterfeed-backend:fork-<sha>` is immutable. It records what ran and is the
    rollback target.
  - Which commit is `fork` right now:

    ```bash
    (set -a; . deploy/.env; set +a
     docker --context "$DOCKER_CONTEXT" image inspect \
       --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
       letterfeed-backend:fork)
    ```

  ## Deploy (switch or update feed-host)

  feed-host's `docker-compose.yml` names `image: letterfeed-backend:fork` with
  `pull_policy: never`. That's a one-time edit in the feed-host repo.

  ```bash
  (
    set -a; . deploy/.env; set +a
    d="$FEED_HOST_DIR"
    # 1. Must list freshrss, letterfeed-backend and letterfeed-frontend:
    docker --context "$DOCKER_CONTEXT" compose --project-directory "$d" -f "$d/docker-compose.yml" config --services
    # 2. Must show letterfeed-backend being recreated:
    docker --context "$DOCKER_CONTEXT" compose --project-directory "$d" -f "$d/docker-compose.yml" up -d --dry-run --no-deps letterfeed-backend
  )
  # 3. If both look right, rerun step 2 without --dry-run.
  ```

  Rebuilds reuse the `fork` tag, so the dry run is also how to confirm compose
  notices the new image ID behind an unchanged tag.

  ## Rollback

  - To an earlier fork build:
    `docker --context "$DOCKER_CONTEXT" tag letterfeed-backend:fork-<oldsha> letterfeed-backend:fork`,
    then the deploy steps above.
  - To the pre-fork overlay image: set feed-host's `image:` back to
    `letterfeed-backend:fix-100` (a feed-host edit), then the deploy steps above.

  ## Checks after a deploy

  ```bash
  (
    set -a; . deploy/.env; set +a
    # Entries carry links:
    curl -s "$LETTERFEED_URL/api/feeds/all" | grep -o '<link href="[^"]*/api/entries/[^"]*" rel="alternate"/>' | head -3
    # The entry page's headers survive the frontend's /api rewrite (GET, not HEAD:
    # the route has no HEAD support):
    id=$(curl -s "$LETTERFEED_URL/api/feeds/all" | grep -o '/api/entries/[A-Za-z0-9_-]*' | head -1 | sed 's#.*/##')
    curl -s -D - -o /dev/null "$LETTERFEED_URL/api/entries/$id" \
      | grep -iE '^(HTTP/|content-type|content-security-policy|x-content-type-options|referrer-policy)'
  )
  ```

  The CSP, `X-Content-Type-Options` and `Referrer-Policy` values must exactly
  equal the ones asserted in `backend/app/tests/test_routers.py`. If they're
  missing or altered after the rewrite, roll back: don't leave an unsandboxed
  entry page running.
  ````

- [ ] **Step 6: Create `deploy/.env`** from `.env.example` with real values. Sources: the git-excluded `$LF/CLAUDE.md` (the docker context, API version and feed-host checkout path are there). For `FRESHRSS_CONTAINER`, run `docker --context <ctx> ps --format '{{.Names}}'` (names only) and pick the FreshRSS one. For `FRESHRSS_USER`, run `docker --context <ctx> exec <container> ls /var/www/FreshRSS/data/users`. Ask the user for `LETTERFEED_URL` if it isn't in the local notes. Never copy values from feed-host's `.env`. Then verify it's ignored and stays out of git:
  ```bash
  git check-ignore -v deploy/.env
  ```
  Expected: a `.gitignore` rule matches (`.env`). If nothing matches, stop.

- [ ] **Step 7: Commit only the two public files.** Never `git add -f deploy/` or `git add -A`: that would add `.env`.
  ```bash
  git add -f deploy/README.md deploy/.env.example
  git status --short   # deploy/.env must NOT appear as staged
  git commit -m "docs(deploy): runbook for building and deploying the fork from source" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  ```

- [ ] **Step 8: Public-content gate, then push.**
  ```bash
  git log -p upstream/master..HEAD | grep -niE '([0-9]{1,3}\.){3}[0-9]{1,3}|/Users/|/home/|~/|\.lan\b|ssh ' || echo "no hits"
  ```
  Also grep for each real value in `deploy/.env` (read it; it isn't secret):
  ```bash
  (set -a; . deploy/.env; set +a; for v in "$LETTERFEED_URL" "$DOCKER_CONTEXT" "$FEED_HOST_DIR" "$FRESHRSS_CONTAINER" "$FRESHRSS_USER"; do git log -p upstream/master..HEAD | grep -qF -- "$v" && echo "HIT: a deploy/.env value appears in history"; done; echo done)
  ```
  Common words like `freshrss` may legitimately appear in the README as the service name; judge any hit by hand, and ask the user if unsure. Then:
  ```bash
  git push -u origin deploy/prod
  ```
  Never open a PR from `deploy/prod`.

---

### Task 8: Build the fork image on the deployment host

**Working directory:** `$LF/.worktrees/deploy-prod`. Requires Task 6.

- [ ] **Step 1: Confirm the worktree is clean** and matches what was pushed: `git status --short` prints nothing (`deploy/.env` is ignored), and `git rev-parse HEAD` equals `git rev-parse origin/deploy/prod`.
- [ ] **Step 2: Build**, as one command:
  ```bash
  cd $LF/.worktrees/deploy-prod && (
    set -a; . deploy/.env; set +a
    sha=$(git rev-parse --short HEAD)
    docker --context "$DOCKER_CONTEXT" buildx build \
      -t letterfeed-backend:fork -t "letterfeed-backend:fork-$sha" \
      --label org.opencontainers.image.source=https://github.com/curiousstranger/LetterFeed \
      --label "org.opencontainers.image.revision=$sha" \
      backend
  )
  ```
  Use a long timeout (up to 10 minutes). The build context is only `backend/`.
- [ ] **Step 3: Verify the image landed in the host's store with the right label:**
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; sha=$(git rev-parse --short HEAD); docker --context "$DOCKER_CONTEXT" image inspect --format '{{.Id}} {{.Architecture}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "letterfeed-backend:fork-$sha" letterfeed-backend:fork letterfeed-backend:fix-100)
  ```
  Expected: `fork-<sha>` and `fork` share one ID, the revision label equals `<sha>`, the architecture matches the host's (the same as `fix-100`'s), and `fix-100` still exists. If `fork-<sha>` is missing, rerun Step 2 with `--load`.

---

### Task 9: Switch feed-host to the fork image and run the live checks

**Working directory:** `$LF/.worktrees/deploy-prod`. The controller runs this task (it has user gates and uses the browser pane).

- [ ] **Step 1: Hand the user the feed-host change. Don't make it.** Tell them: in `$FEED_HOST_DIR/docker-compose.yml`, change the `letterfeed-backend` service's `image: letterfeed-backend:fix-100` to `image: letterfeed-backend:fork`, keeping `pull_policy: never`. Wait for them to confirm it's done (and committed or PR'd in feed-host, at their discretion).
- [ ] **Step 2: Check the checkout:**
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; d="$FEED_HOST_DIR"; docker --context "$DOCKER_CONTEXT" compose --project-directory "$d" -f "$d/docker-compose.yml" config --services)
  ```
  Expected: the list includes `freshrss`, `letterfeed-backend` and `letterfeed-frontend`. Anything else: stop.
- [ ] **Step 3: Dry run:**
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; d="$FEED_HOST_DIR"; docker --context "$DOCKER_CONTEXT" compose --project-directory "$d" -f "$d/docker-compose.yml" up -d --dry-run --no-deps letterfeed-backend)
  ```
  Expected: it recreates `letterfeed-backend` only. If it touches any other service, or doesn't recreate the backend, stop and report.
- [ ] **Step 4: Apply:** the same command without `--dry-run`. Then confirm it's running and on the fork image (names and image only, no env):
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; d="$FEED_HOST_DIR"; docker --context "$DOCKER_CONTEXT" compose --project-directory "$d" -f "$d/docker-compose.yml" ps --format '{{.Service}} {{.Image}} {{.Status}}')
  ```
- [ ] **Step 5: Live check 1, links in the feed:**
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; curl -s "$LETTERFEED_URL/api/feeds/all" | grep -o '<link href="[^"]*/api/entries/[^"]*" rel="alternate"/>' | head -3)
  ```
  Expected: three lines, each with an href under `$LETTERFEED_URL/api/entries/`.
- [ ] **Step 6: Live check 2, exact headers after the Next.js rewrite.** Use GET, not `curl -I`: the route has no HEAD support, and HEAD returns 405.
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a
  id=$(curl -s "$LETTERFEED_URL/api/feeds/all" | grep -o '/api/entries/[A-Za-z0-9_-]*' | head -1 | sed 's#.*/##')
  h=$(curl -s -D - -o /dev/null "$LETTERFEED_URL/api/entries/$id" | tr -d '\r')
  echo "$h" | head -1
  want_csp="sandbox allow-popups allow-popups-to-escape-sandbox; default-src 'none'; img-src * data:; style-src * 'unsafe-inline'; font-src * data:; media-src *; form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
  [ "$(echo "$h" | grep -i '^content-security-policy:' | sed 's/^[^:]*: //')" = "$want_csp" ] && echo "CSP ok" || echo "CSP MISMATCH"
  [ "$(echo "$h" | grep -i '^x-content-type-options:' | sed 's/^[^:]*: //')" = "nosniff" ] && echo "nosniff ok" || echo "nosniff MISMATCH"
  [ "$(echo "$h" | grep -i '^referrer-policy:' | sed 's/^[^:]*: //')" = "no-referrer" ] && echo "referrer ok" || echo "referrer MISMATCH"
  echo "$h" | grep -i '^content-type:')
  ```
  Expected: `HTTP/... 200`, `CSP ok`, `nosniff ok`, `referrer ok`, `content-type: text/html; charset=utf-8`. **Any MISMATCH or missing header: roll back immediately** (tag `fix-100` path: ask the user to revert the `image:` line, then Steps 2–4) and report. Don't leave an unsandboxed page running.
- [ ] **Step 7: Live check 3.** Open `$LETTERFEED_URL/api/entries/<id>` (the id from Step 6) in the browser pane. Confirm it renders and that clicking a link in the newsletter opens it. Report the result; don't paste the URL into anything committed.

---

### Task 10: FreshRSS: confirm existing entries pick up the links

**Working directory:** `$LF/.worktrees/deploy-prod`. The controller runs this task (user gates). All commands have this shape:
```bash
cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; docker --context "$DOCKER_CONTEXT" exec -u www-data "$FRESHRSS_CONTAINER" php -r '<PHP>' "$FRESHRSS_USER")
```
The PHP reads the username from `$argv[1]` and opens `new PDO("sqlite:/var/www/FreshRSS/data/users/{$argv[1]}/db.sqlite")`. Never `cat` any FreshRSS config file.

- [ ] **Step 1: Confirm the table names** before querying (`SELECT name FROM sqlite_master WHERE type='table'`). The steps below assume `feed` and `entry`; adapt if they differ.
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; docker --context "$DOCKER_CONTEXT" exec -u www-data "$FRESHRSS_CONTAINER" php -r '$db=new PDO("sqlite:/var/www/FreshRSS/data/users/{$argv[1]}/db.sqlite"); foreach($db->query("SELECT name FROM sqlite_master WHERE type=\"table\"") as $r) echo $r[0],"\n";' "$FRESHRSS_USER")
  ```
- [ ] **Step 2: Fact 1, the subscribed LetterFeed URLs** (the `url` column only):
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; docker --context "$DOCKER_CONTEXT" exec -u www-data "$FRESHRSS_CONTAINER" php -r '$db=new PDO("sqlite:/var/www/FreshRSS/data/users/{$argv[1]}/db.sqlite"); foreach($db->query("SELECT id, url FROM feed WHERE url LIKE \"%/api/feeds/%\" OR url LIKE \"%/feeds/%\"") as $r) echo $r["id"]," ",$r["url"],"\n";' "$FRESHRSS_USER")
  ```
  Note whether FreshRSS subscribes to per-newsletter feeds (they return every entry) or only `/feeds/all`. The master feed returns only `MASTER_FEED_LIMIT` (100) entries, so older entries would never be refreshed.
- [ ] **Step 3: Fact 2, `mark_updated_article_unread`.** Extract **only that key**:
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; docker --context "$DOCKER_CONTEXT" exec -u www-data "$FRESHRSS_CONTAINER" php -r '$c=include "/var/www/FreshRSS/data/users/{$argv[1]}/config.php"; var_export(array_key_exists("mark_updated_article_unread",$c) ? $c["mark_updated_article_unread"] : "unset"); echo "\n";' "$FRESHRSS_USER")
  ```
  If it prints `unset`, read the default the same way, one key only, from `/var/www/FreshRSS/config-user.default.php`. **If the effective value is `true`, stop and ask the user**: a refresh would mark every updated entry unread.
- [ ] **Step 4: Baseline.** Pick one small LetterFeed feed id from Step 2. Record `id`, `guid`, `link` and `hex(hash)` for up to 5 of its entries, plus the dummy-link entries:
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; docker --context "$DOCKER_CONTEXT" exec -u www-data "$FRESHRSS_CONTAINER" php -r '$db=new PDO("sqlite:/var/www/FreshRSS/data/users/{$argv[1]}/db.sqlite"); $q=$db->prepare("SELECT id, guid, link, hex(hash) h FROM entry WHERE id_feed=? OR link LIKE ? ORDER BY id DESC LIMIT 10"); $q->execute([$argv[2], "%linktest=%"]); foreach($q as $r) echo $r["id"]," ",$r["guid"]," [",$r["link"],"] ",$r["h"],"\n";' "$FRESHRSS_USER" <FEED_ID>)
  ```
  (Replace `<FEED_ID>` inline in the terminal only.)
- [ ] **Step 5: Refresh that one feed.** Ask the user to click that feed's refresh ("Actualize") in the FreshRSS UI, or, with their OK, run `cli/actualize-user.php --user "$FRESHRSS_USER"` in the container, which refreshes every feed. Then rerun Step 4's query. Expected: `link` = `$LETTERFEED_URL/api/entries/<id>` matching the guid's id, a changed hash, and the dummy `?linktest=` links replaced.
- [ ] **Step 6: After the next normal cron refresh**, count the remaining link-less LetterFeed entries:
  ```bash
  cd $LF/.worktrees/deploy-prod && (set -a; . deploy/.env; set +a; docker --context "$DOCKER_CONTEXT" exec -u www-data "$FRESHRSS_CONTAINER" php -r '$db=new PDO("sqlite:/var/www/FreshRSS/data/users/{$argv[1]}/db.sqlite"); echo $db->query("SELECT count(*) FROM entry WHERE guid LIKE \"urn:letterfeed:entry:%\" AND link = \"\"")->fetchColumn(),"\n";' "$FRESHRSS_USER")
  ```
  Expected: 0, or only entries LetterFeed no longer serves (for example, older than the master feed's 100 when only `/feeds/all` is subscribed).
- [ ] **Step 7 (only if links didn't update):** a backfill.
  1. Online backup: run `$db->exec("VACUUM INTO \"/var/www/FreshRSS/data/users/{$argv[1]}/db.sqlite.bak-20260921-backfill\"")` via the same wrapper, and confirm the file exists (`ls -l` in the container).
  2. Dry run in a rolled-back transaction: `BEGIN; UPDATE entry SET link = :base || '/api/entries/' || substr(guid, 22) WHERE guid LIKE 'urn:letterfeed:entry:%' AND (link = '' OR link LIKE '%linktest=%'); SELECT changes(); ROLLBACK;`. `substr(guid, 22)` skips the 21-character `urn:letterfeed:entry:` prefix. Bind `:base` to `$LETTERFEED_URL` passed as `$argv[2]`, and print the row count plus three sample rows computed with the same expression via `SELECT`.
  3. Hand the user the apply command (the same statement with `COMMIT`) to run themselves. Don't run it.
- [ ] **Step 8: Acceptance.** Ask the user to check on their device that newsletter articles now appear in Current.

---

### Task 11: Retire the overlay and legacy `deploy/` (user gates)

**Working directory:** the main checkout `$LF`, for the legacy directory only, and only with the user's OK.

- [ ] **Step 1:** Once Task 9's live checks have passed, ask the user whether to delete the untracked legacy `$LF/deploy/` (the overlay files, the old README and `cleanup-orphan-newsletters.py`). List its contents first (`ls -la`). The `fix-100` image stays on the host until the user says otherwise.
- [ ] **Step 2 (on a yes):** delete the directory, then remove the `/deploy/` line from `$LF/.git/info/exclude` (shared by every worktree). Show the file's before/after lines. Afterwards, `git -C $LF/.worktrees/deploy-prod status --short` must still show nothing (`deploy/.env` is ignored through `.gitignore`).
- [ ] **Step 3: Propose, don't make,** corrections to the local `CLAUDE.md`'s deployment section:
  - It now runs `letterfeed-backend:fork`, built from `deploy/prod`, with `fix-100` as the rollback.
  - buildx is installed.
  - `frontend/Dockerfile` has no BuildKit-only syntax, so the claim that frontend changes need buildx was wrong.
  - Point to `deploy/README.md` on `deploy/prod` and to `deploy/.env`.

  Also propose updating the "Pending upstream fixes" table to add `feat/entry-links`.
