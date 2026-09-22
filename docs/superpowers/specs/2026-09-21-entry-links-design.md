# Per-entry links in LetterFeed feeds: design

Date: 2026-09-21
Branch: `feat/entry-links` (off `upstream/master` @ 454c27b)
Worktree: `.worktrees/entry-links` (relative to the LetterFeed checkout)

This file is published with the fork, so it holds no deployment specifics.
Host addresses, usernames, container names and local paths are referred to
only by the variable names defined in [Deployment variables](#deployment-variables).

## Problem

`_add_entries_to_feed` in `backend/app/services/feed_generator.py` never emits an
entry `<link>`. A link-less entry with content is valid Atom (RFC 4287), but
downstream readers handle it badly:

- FreshRSS stores every LetterFeed entry with `link = ""` and serves them over
  the Google Reader API with empty `canonical`/`alternate` hrefs.
- The Current app silently drops articles with an empty URL. Giving a few
  entries a dummy link in FreshRSS's DB made exactly those entries appear in
  Current (2026-09-21).

A real per-article URL is also useful on its own: open, share, save to a
read-later service.

## Goals

- Every entry in every feed (per-newsletter and master) carries
  `<link href="<APP_BASE_URL>/api/entries/<entry.id>"/>`.
- That URL renders the stored entry body as a standalone page, sandboxed so the
  newsletter's HTML can't act against the LetterFeed UI or API.
- It's small, based on `master`, and general enough for a possible upstream PR.
  **No upstream PR without asking first.**
- Note: feedgen 1.0.0's `FeedEntry.atom_entry` rebinds its loop variable, so
  the `rel="alternate"` passed to `fe.link(...)` is never serialized. RFC 4287
  §4.2.7.2 makes a link with no `rel` mean `rel="alternate"`, so the emitted
  `<link>` is still correct.

## Upstream context: issue #19

[LeonMusCoden/LetterFeed#19](https://github.com/LeonMusCoden/LetterFeed/issues/19),
"Feat - Add Link Attribute and Hosted HTML Page" (open, `enhancement`, opened
2025-09-12 by gharden91), asks for exactly this, for **per-entry** links:

- **The request:** a Miniflux user wants each entry's title to go to a hosted
  copy of the email's HTML. They suggest adding a `<link>` to entries and keying
  the page by the entry id from `urn:letterfeed:entry:<id>`.
- **The maintainer (LeonMusCoden):** summarized it as an entry linking to
  LetterFeed, where the raw HTML of the entry is served, and called it "a good
  addition!"
- **Another commenter (KindOfNerdy):** asked for more: a customizable page
  template (their own logo, a dark/light toggle) with the article in its
  `<body>`. The maintainer said that isn't the same request. It's out of scope
  here (see Non-goals).

So an upstream PR from this branch implements an enhancement the maintainer has
already welcomed, not an unsolicited feature. The design matches his reading:
link to LetterFeed and serve the raw stored HTML. The PR description should say
"Closes #19", state that the template idea isn't included, and summarize the
[Security model](#security-model). The reader-compatibility angle (Current drops
link-less articles) is supporting motivation.

#19 covers only the entries' links. The feed-level `rel="self"` bug below has
no upstream issue or PR (searched 2026-09-21).

## Non-goals

- Fixing the feed's own `rel="self"` link. This is a separate upstream bug with
  no existing issue. `feed_generator.py` builds it as `APP_BASE_URL + /feeds/...`,
  but `APP_BASE_URL` is the frontend URL (`.env.example`), upstream's compose
  publishes only the frontend, and the frontend forwards only `/api/*` to the
  backend. So the advertised self URL 404s in upstream's documented deployment.
  It doesn't cause the missing articles (readers fetch from the subscribed
  `/api/feeds/...` URL), so it gets its own small fix branch later.
- Any wrapper around the entry: a customizable template, logo, dark/light
  toggle, or LetterFeed UI chrome. This was proposed twice: as a frontend page
  (approach B) and in the KindOfNerdy comment on #19, which the maintainer said
  isn't the same request. Either form needs a frontend page, a backend JSON
  endpoint and a second image to build and deploy, all for cosmetics. The page
  serves the stored HTML as is. A wrapper could be added later behind the same
  `/api/entries/<id>` URL, so links already in readers wouldn't change.
- Using the email's own "View in browser" URL (approach C, rejected: often
  missing, it's a tracking redirect, and it needs per-sender heuristics).
- HEAD support, caching headers, plain-text-specific rendering, and an option to
  block remote images.

## Evidence behind the decisions

- **URL path.** On a real deployment where `APP_BASE_URL` is the frontend,
  `<APP_BASE_URL>/feeds/all` returns a 404 from Next.js and
  `<APP_BASE_URL>/api/feeds/all` returns 200 Atom (checked 2026-09-21). The
  frontend middleware (`frontend/src/middleware.ts`) rewrites `/api/*` to the
  backend with the `/api` prefix stripped. `.env.example` documents
  `APP_BASE_URL` as the frontend URL (`http://localhost:3000`). So the backend
  route `/entries/{id}` is published at `<APP_BASE_URL>/api/entries/{id}`.
- **Ids.** The Atom `<id>` stays `urn:letterfeed:entry:<entry.id>`. Changing it
  would make every reader treat all entries as new, and a URN is independent of
  the hostname. The link reuses the same nanoid (`entries.id`, the primary key,
  URL-safe alphabet `A-Za-z0-9_-`), so no escaping is needed.
- **Auth.** `/feeds/*` is public by design, because feed readers can't
  authenticate. An entry page exposes exactly what the feed already exposes, so
  `/entries/*` is public too (registered without `protected_route`). See the
  [Security model](#security-model) for why that's no new exposure.
- **FreshRSS update.** `FreshRSS_Entry::hash()` (FreshRSS 1.30.0,
  `app/Models/Entry.php:518`) is
  `md5(link . title . authors . originalContent . tags . attributes)`. Adding a
  link changes the hash, so FreshRSS should update existing entries it still
  sees in a feed. This is still verified empirically (see Deploy).

## Backend changes

### `app/crud/entries.py`

Add `get_entry(db, entry_id: str) -> Entry | None`: a primary-key lookup
following the file's existing style (debug log, `db.query(Entry)...first()`).

### `app/routers/entries.py` (new)

```
GET /entries/{entry_id}
  200: entry.body as-is, media_type "text/html; charset=utf-8", + safety headers
  404: {"detail": "Entry not found"}   (HTTPException, like routers/feeds.py)
```

The body is served exactly as stored, whether that's a full HTML email,
nh3-cleaned partial HTML, or the plain-text fallback. It's the same content the
Atom `<content type="html">` carries. Log the entry id only, never the body.

The safety headers are defined once as a module-level constant:

```
Content-Security-Policy: sandbox allow-popups allow-popups-to-escape-sandbox;
    default-src 'none'; img-src * data:; style-src * 'unsafe-inline';
    font-src * data:; media-src *; form-action 'none'; base-uri 'none';
    frame-ancestors 'none'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
```

(These are sent as a single header line; the wrapping above is only for
readability.)

### `app/main.py`

`app.include_router(entries.router)`, with no auth dependency, next to
`feeds.router`.

### `app/services/feed_generator.py`

- Add a helper `_entry_url(entry_id) -> str` that returns
  `f"{settings.app_base_url.rstrip('/')}/api/entries/{entry_id}"`, with a
  comment explaining that `/api` is how the frontend exposes the backend and
  that `APP_BASE_URL` is the frontend URL.
- In `_add_entries_to_feed`: `fe.link(href=_entry_url(entry.id), rel="alternate")`.
  Because it's shared, both `generate_feed` and `generate_master_feed` get it.

## Security model

The page serves untrusted, sender-controlled HTML on the same origin as the
LetterFeed UI and `/api`. Audited against the code on 2026-09-21.

### What protects the UI and API

- **No script, and an opaque origin.** `sandbox` without `allow-scripts` or
  `allow-same-origin` disables JS and gives the page a unique opaque origin. The
  UI keeps its auth token in `localStorage` (`frontend/src/contexts/AuthContext.tsx`,
  `frontend/src/lib/api.ts`), which an opaque origin can't read. Auth is a
  Bearer header set by JS; LetterFeed sets no cookies, so requests from the page
  carry no credentials. `default-src 'none'` (no `connect-src`, frames, objects
  or workers) is defense in depth.
- **No form posts.** `form-action 'none'`, plus the sandbox without
  `allow-forms`. This also rules out on-origin credential phishing: a fake
  "log in" form can't submit.
- **No framing, no base hijack.** `frame-ancestors 'none'` stops other sites
  from framing the page. `base-uri 'none'` stops a `<base>` tag from redirecting
  relative URLs.
- **Nothing leaks in Referer headers.** `Referrer-Policy: no-referrer` keeps the
  LetterFeed host and entry ids out of requests to trackers and linked sites.
- **No reinterpretation.** `nosniff` stops the browser from treating the body as
  another content type.
- **No new exposure.** Every servable entry is already in a public feed.
  Per-newsletter feeds are unlimited, and deleting a newsletter deletes its
  entries (`cascade="all, delete-orphan"` in `models/newsletters.py`), so
  there are no orphan pages. Ids are 21-character nanoids (~126 bits), not
  guessable. The path parameter can't contain `/`, is looked up through the ORM,
  and a 404 reveals nothing. feedgen escapes the href in the feed XML.

### Invariant this introduces

**LetterFeed must never add a state-changing GET route.** The sandbox doesn't
stop same-origin subresource requests: `<img src="/api/...">` still sends a GET.
Today every GET route is read-only (`/auth/status`, `/health`, `/imap/settings`,
`/imap/folders`, `/feeds/*`, `/newsletters*`), and without JS or credentials the
response can't be read (`/imap/settings` also excludes passwords from its
response). Put this in a code comment next to the header constant and in the
upstream PR description.

### Accepted risks

- **Remote content loads.** Images, styles, fonts and media load from anywhere,
  so tracking pixels see the reader's IP when the page opens, just as they do
  when FreshRSS or Current renders the same content. Blocking them would break
  newsletter layouts.
- **LAN requests.** `img-src *` lets a newsletter point image requests at
  private-network addresses (a router's admin page, for example). This is the
  generic risk of rendering email HTML, and an ordinary link is no different.
- **Unsandboxed popups.** `allow-popups-to-escape-sandbox` makes a
  `target="_blank"` link open a normal, unsandboxed page, which is equivalent to
  clicking a link in any mail client. Without it, most "Read more" links break.
- **Load.** Anyone who can reach LetterFeed can fetch large bodies without
  authenticating, the same load as fetching a feed.
- **Browser support.** Enforcement relies on browser support for the CSP
  `sandbox` directive, which all current engines (Chromium, WebKit, Gecko) have.

### Caveat for users: a link is the whole email

The page is the raw email, including personalized unsubscribe, "view in
browser" and sometimes magic-login links. That isn't new exposure, since the
feed already carries the same content. But sharing an entry URL, or saving it to
a service that fetches it, shares those links too. Say so in the upstream PR,
and in the README if the maintainer wants user-facing docs.

## Tests (TDD: each one watched failing on unmodified code first)

- `app/tests/services/test_feed_generator.py`: real `Newsletter`/`Entry` rows in
  the test DB. Parse the output of `generate_feed` and `generate_master_feed`
  with `xml.etree.ElementTree` and assert each `<entry>` has exactly one
  `<link href="<base>/api/entries/<id>"/>`. Also assert
  that a trailing slash on `app_base_url` doesn't produce `//api`.
- `app/tests/test_crud.py`: `get_entry` returns the row, and returns `None` for
  an unknown id.
- `app/tests/test_routers.py`:
  - An existing id returns 200 with the exact stored body and a `text/html`
    content type.
  - The CSP, `X-Content-Type-Options` and `Referrer-Policy` headers each
    **equal** a string literal written out in the test. Don't import the
    module constant, or the test compares the code to itself. Browsers silently
    ignore a malformed directive, so a typo like a missing `;` fails open;
    exact-match tests make any change to the policy visible in review.
  - An unknown id returns 404.
  - With auth credentials configured, the endpoint still returns 200 without a
    token.
- The gauntlet, from `backend/`: `uv sync --group test`, `uv run pytest`,
  `uv run ruff check .` and `uv run ruff format --check app`. Paste the real
  output of each.

### Adversarial browser check (before merging)

Unit tests can only prove which headers are sent, not that a browser enforces
them. So:

1. Run the branch's backend locally with a throwaway SQLite DB.
2. Seed one newsletter and one entry through the API
   (`POST /newsletters/{id}/entries`) whose body contains these vectors. Each
   one, if it executes, requests a unique `/canary/<vector>` path on the local
   backend:
   - an inline `<script>`
   - `<img src=x onerror=...>`
   - a `javascript:` link, both plain and with `target="_blank"`
   - a `<form>` posting to a canary, with a submit button
   - `<iframe>`, `<object>` and `<embed>` pointing at canaries
   - `<meta http-equiv="refresh" content="0;url=javascript:...">`
   - `<base href="/canary/base/">` followed by a relative `<img src="x.png">`
   - one control, a plain `<img src="/canary/control">`, which **must** load
3. Open the entry in the browser pane, then click every link and button.
4. It passes only if the backend's access log shows `/canary/control` and no
   other canary path, and an ordinary `target="_blank"` link still opens a new
   tab.
5. Record the log excerpt in the PR description. The fixture HTML goes in the
   PR too, so reviewers can repeat the check.

## Branch and PR

- The work is on `feat/entry-links`. The branch has no upstream tracking; push
  with `git push -u origin feat/entry-links`.
- `gh pr create` targets **`curiousstranger/LetterFeed` `master`**.
- This spec is committed on the branch for the fork PR. **Drop it from any
  upstream-bound branch.**
- Nothing that's pushed may contain deployment specifics: not the spec, the
  plan, commit messages or PR text. Use the variable names below.

## Deploy

This section is the fork's own deployment: the `feed-host` stack on a remote Docker host, which
runs LetterFeed behind FreshRSS.

### Deployment variables

Deployment specifics live in `deploy/.env` on the `deploy/prod` branch. It's
git-ignored (`.gitignore`'s `.env` pattern matches at any depth), and a
committed `deploy/.env.example` documents it with placeholder values. Docs,
plans and commands refer to these values only by name:

| Variable | Meaning |
|---|---|
| `LETTERFEED_URL` | The deployment's public LetterFeed URL (its `APP_BASE_URL`, i.e. the frontend) |
| `DOCKER_CONTEXT` | The docker context for the deployment host. The Docker CLI reads this variable itself (see Constraints) |
| `DOCKER_API_VERSION` | The API version the host's daemon needs |
| `FEED_HOST_DIR` | The feed-host checkout whose compose file defines the LetterFeed services |
| `FRESHRSS_CONTAINER` | The FreshRSS container name |
| `FRESHRSS_USER` | The FreshRSS username, whose DB is `/var/www/FreshRSS/data/users/$FRESHRSS_USER/db.sqlite` |

Load them with `set -a; . <deploy-prod worktree>/deploy/.env; set +a`. This file
isn't secret, so reading it is fine. feed-host has its **own** `.env`, which
holds live credentials: never read or print it, and never run bare
`docker compose config` in `$FEED_HOST_DIR`.

Constraints: always pass `--context "$DOCKER_CONTEXT"`, never SSH to the
host, and run compose only from `$FEED_HOST_DIR`.

The Docker CLI reads `DOCKER_CONTEXT` (and `DOCKER_API_VERSION`) from the
environment itself. So once `deploy/.env` is sourced, every `docker` command in
that shell targets the deployment host, including ones meant for a local
daemon. Source it only inside a subshell or a single command, never into an
interactive shell's startup files. Passing `--context` explicitly anyway makes
each command's target obvious when it's read.

### The `deploy/` directory moves to `deploy/prod`

Today `deploy/` is an untracked directory in the main checkout, hidden by
`/deploy/` in `.git/info/exclude`. It becomes committed content on
`deploy/prod`, the fork-only integration branch, so it's versioned alongside the
code it deploys.

- **Written generically.** `deploy/prod` is pushed to the public fork, so
  everything committed follows the same rule as this spec: values stay in
  `deploy/.env`.
- **What moves:** a rewritten `deploy/README.md` (buildx setup, `deploy/prod`,
  build, tags, switching feed-host, rollback, checks) and a new
  `deploy/.env.example`.
- **What doesn't move:** the overlay files (`Dockerfile`, `newsletters.py`,
  `router_newsletters.py`, `letterfeed-fix.override.yml`), which this design
  retires. Nor does `cleanup-orphan-newsletters.py`, a one-off already run that
  may embed instance data. They stay in the untracked main-checkout `deploy/`.
- **Adding files:** while the legacy exclude line exists, add them with
  `git add -f`. Tracked files aren't affected by excludes after that.
- **Retiring the legacy directory:** once the fork image is verified live, and
  only with the user's OK, delete the untracked main-checkout `deploy/`. Then
  remove the `/deploy/` line from `.git/info/exclude`, which every worktree
  shares.

### Image: built from source, not overlaid

This replaces the COPY overlay. That overlay started from upstream's binary
`:latest` plus loose `.py` files, was valid only while the base matched
`master`, and needed a new COPY and guard entry for every change.

**Why the overlay existed.** Docker CLI 23+ sends `docker build` through the
buildx plugin. Homebrew's `docker` formula doesn't include it, so builds needed
`DOCKER_BUILDKIT=0`. The legacy builder can't parse `backend/Dockerfile`'s
`RUN --mount=type=cache`. The deployment host's daemon (Docker 27) has BuildKit built in, and
builds against its context run natively on the host. Only the Mac's
client plugin was missing.

1. **Install buildx on the Mac, one time.** Run `brew install docker-buildx` and
   follow its caveat (add `cliPluginsExtraDirs` to `~/.docker/config.json`).
   This changes the user's machine, so get the user's explicit OK first, or
   let them run it. Verify with `docker buildx version` and
   `docker --context "$DOCKER_CONTEXT" buildx ls`.
2. **Integration branch `deploy/prod` on the fork.** It's `upstream/master` with
   these merged in: `fix/processor-sees-all-newsletters` (e84e1bb),
   `fix/newsletters-endpoint-returns-all` (044fabc) and `feat/entry-links`,
   plus the `deploy/` content above. These touch disjoint files, so no
   conflicts are expected.
   - Push it to `origin` so every built SHA can be recovered.
   - **Never open a PR from it.** Feature and fix branches stay small and
     upstream-shaped; only `deploy/prod` combines them.
   - Update it by merging again: a feature branch's new commits, or
     `upstream/master` when upstream moves. When a fix ships upstream, its
     merge becomes a no-op.
3. **Build from a clean checkout** of `deploy/prod` in its own worktree,
   `.worktrees/deploy-prod`. `backend/` has no `.dockerignore`, so a dev checkout
   would upload `.venv` as build context. Only `backend/` is sent, so
   `deploy/.env` never enters the image. Build with the repo's own
   `backend/Dockerfile`:

   ```bash
   set -a; . .worktrees/deploy-prod/deploy/.env; set +a
   sha=$(git -C .worktrees/deploy-prod rev-parse --short HEAD)
   docker --context "$DOCKER_CONTEXT" buildx build \
     -t letterfeed-backend:fork -t "letterfeed-backend:fork-$sha" \
     --label org.opencontainers.image.source=https://github.com/curiousstranger/LetterFeed \
     --label "org.opencontainers.image.revision=$sha" \
     .worktrees/deploy-prod/backend
   ```

   The build must land in the host's image store (buildx's `docker` driver for
   that context). Confirm it did with
   `docker --context "$DOCKER_CONTEXT" image inspect letterfeed-backend:fork-$sha`.
   If a different builder is selected, add `--load`. Base images are pinned by
   tag, not digest, the same as upstream, and `uv sync --frozen` installs from
   the committed lockfile.
4. **Tags.**
   - `fork` is the moving tag feed-host names, so later deploys need no
     compose edit.
   - `fork-<sha>` is immutable. It's the record of what ran and the rollback
     target.
   - `docker --context "$DOCKER_CONTEXT" image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' letterfeed-backend:fork`
     reports the running commit.
5. **Retire the overlay.**
   - The overlay files stay in the legacy main-checkout `deploy/` until it's
     deleted (see above).
   - The `fix-100` image stays on the host until the user says to remove it.
   - Propose (don't make) corrections to the local notes: the buildx note, and
     the claim that frontend changes need buildx. `frontend/Dockerfile` has no
     BuildKit-only syntax.

### Switching feed-host

1. Hand the user the one-line change to feed-host's `docker-compose.yml`
   (`image: letterfeed-backend:fork`, keeping `pull_policy: never`). **The user
   makes it; don't edit feed-host.**
2. Check the checkout with
   `docker compose --project-directory "$FEED_HOST_DIR" -f "$FEED_HOST_DIR/docker-compose.yml" config --services`.
   Expect `freshrss`, `letterfeed-backend` and `letterfeed-frontend`.
3. From `$FEED_HOST_DIR`, run
   `docker --context "$DOCKER_CONTEXT" compose up -d --dry-run --no-deps letterfeed-backend`
   first and confirm it recreates the container. Then run it without
   `--dry-run`. Later rebuilds reuse the `fork` tag, so the dry run is also how
   to confirm compose notices the new image ID behind an unchanged tag.
4. Rollback:
   - To an earlier fork build: `docker --context "$DOCKER_CONTEXT" tag letterfeed-backend:fork-<oldsha> letterfeed-backend:fork`, then the same `up -d`.
   - To the pre-fork image: `image: letterfeed-backend:fix-100` (the user edits
     feed-host), then `up -d`.

### Live checks

1. `curl -s "$LETTERFEED_URL/api/feeds/all"` shows
   `<link href=".../api/entries/<id>"/>` on entries.
2. `curl -sI "$LETTERFEED_URL/api/entries/<id>"` shows 200, and its CSP,
   `nosniff` and `no-referrer` headers **exactly equal** the values in the unit
   tests, even **after the Next.js rewrite**. If they're missing or altered,
   roll back and redesign; don't leave an unsandboxed page running.
3. Open one real entry in the browser pane and check that it renders and that
   links open.

### FreshRSS: do existing entries pick up the links?

Use `docker --context "$DOCKER_CONTEXT" exec -u www-data "$FRESHRSS_CONTAINER" php ...`
against the DB path above. A backup from before the dummy-link test exists next
to the DB (`db.sqlite.bak-20260921-linktest`).

1. **Before any refresh, read two facts:**
   - Which LetterFeed URLs FreshRSS is subscribed to (the feed table's `url`
     column only). The per-newsletter feeds return all entries; `/feeds/all`
     returns only `MASTER_FEED_LIMIT` (100), so older entries would never be
     seen again.
   - The user's `mark_updated_article_unread` setting. Extract **only that key**
     with a one-line PHP `include` that prints it. Never `cat` or dump the
     user's `config.php`, which also holds API password hashes. **If it's on,
     stop and ask the user**, because updating every entry would mark them all
     unread.
2. Record a baseline of `link` and `hash` for a few entries in one small
   LetterFeed feed, including one of the entries with a dummy `?linktest=<id>`
   link.
3. Refresh that one feed, then re-query. Expect `link` to be
   `.../api/entries/<id>` and the dummy link replaced.
4. After the normal cron refresh, count LetterFeed entries with `link = ''`.
   Expect 0, or only entries LetterFeed no longer serves.
5. **Only if links don't update:** a one-off backfill of FreshRSS's link column.
   Take an online backup first, dry-run it in a rolled-back transaction, and
   hand the user the apply command to run themselves.
6. Acceptance: newsletter articles appear in Current. The user checks this on
   their device.
