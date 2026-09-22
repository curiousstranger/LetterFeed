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

Both images are built from the fork, because fork changes land in both. A
backend-only deploy silently ships half a feature: the OPML export's endpoint
without its button.

Build from the clean `deploy/prod` worktree. Neither `backend/` nor `frontend/`
has a `.dockerignore`, so a worktree that has had tests run in it would upload
`.venv` (135M) or `node_modules` (534M) as build context — and the frontend
Dockerfile's `COPY . .` would drop a macOS-native `node_modules` on top of the
image's Linux one. Delete `backend/.venv`, `frontend/node_modules`,
`frontend/.next` and `frontend/.swc` first; `git status` being clean does not
mean the build context is. Only the one service directory is sent, so
`deploy/.env` never enters either image.

```bash
(
  set -a; . deploy/.env; set +a
  sha=$(git rev-parse --short HEAD)
  for svc in backend frontend; do
    docker --context "$DOCKER_CONTEXT" buildx build \
      -t "letterfeed-$svc:fork" -t "letterfeed-$svc:fork-$sha" \
      --label org.opencontainers.image.source=https://github.com/curiousstranger/LetterFeed \
      --label "org.opencontainers.image.revision=$sha" \
      "$svc"
    docker --context "$DOCKER_CONTEXT" image inspect --format '{{.Id}}' "letterfeed-$svc:fork-$sha"
  done
)
```

The image must land in the host's image store (buildx's `docker` driver for
that context). If `image inspect` can't find it, a different builder was
selected; rerun with `--load`.

The frontend reaches the backend through `src/middleware.ts`, which reads
`LETTERFEED_BACKEND_URL` at runtime. Nothing about the backend's address is
baked into the image, so feed-host's existing environment keeps working.

## Tags

- `letterfeed-backend:fork` and `letterfeed-frontend:fork` are the moving tags
  feed-host names, so a new deploy needs no compose edit.
- `letterfeed-<svc>:fork-<sha>` is immutable. It records what ran and is the
  rollback target.
- Which commit each `fork` tag is right now:

  ```bash
  (set -a; . deploy/.env; set +a
   for svc in backend frontend; do
     docker --context "$DOCKER_CONTEXT" image inspect \
       --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
       "letterfeed-$svc:fork"
   done)
  ```

## Deploy (switch or update feed-host)

feed-host's `docker-compose.yml` names `image: letterfeed-backend:fork` and
`image: letterfeed-frontend:fork`, both with `pull_policy: never`. That's a
one-time edit in the feed-host repo.

```bash
(
  set -a; . deploy/.env; set +a
  d="$FEED_HOST_DIR"
  # 1. Must list freshrss, letterfeed-backend and letterfeed-frontend:
  docker --context "$DOCKER_CONTEXT" compose --project-directory "$d" -f "$d/docker-compose.yml" config --services
  # 2. Must show both LetterFeed containers being recreated:
  docker --context "$DOCKER_CONTEXT" compose --project-directory "$d" -f "$d/docker-compose.yml" up -d --dry-run --no-deps letterfeed-backend letterfeed-frontend
)
# 3. If both look right, rerun step 2 without --dry-run.
```

Rebuilds reuse the `fork` tag, so the dry run is also how to confirm compose
notices the new image ID behind an unchanged tag.

## Rollback

- To an earlier fork build:
  `docker --context "$DOCKER_CONTEXT" tag letterfeed-<svc>:fork-<oldsha> letterfeed-<svc>:fork`,
  then the deploy steps above. The two images carry the same `<sha>`, so roll
  both back together unless you know the change was one-sided.
- To the pre-fork overlay image: set feed-host's `image:` back to
  `letterfeed-backend:fix-100` (a feed-host edit), then the deploy steps above.

## Checks after a deploy

```bash
(
  set -a; . deploy/.env; set +a
  # Entries carry links:
  curl -s "$LETTERFEED_URL/api/feeds/all" | grep -o '<link href="[^"]*/api/entries/[^"]*"' | head -3
  # The entry page's headers survive the frontend's /api rewrite (GET, not HEAD:
  # the route has no HEAD support):
  id=$(curl -s "$LETTERFEED_URL/api/feeds/all" | grep -o '/api/entries/[A-Za-z0-9_-]*' | head -1 | sed 's#.*/##')
  curl -s -D - -o /dev/null "$LETTERFEED_URL/api/entries/$id" \
    | grep -iE '^(HTTP/|content-type|content-security-policy|x-content-type-options|referrer-policy)'
  # OPML export is served and protected. Unauthenticated: 401 when auth is on.
  # With a token, outline count should match the active newsletter count:
  curl -s -D - -o /dev/null "$LETTERFEED_URL/api/newsletters/opml" | grep -iE '^(HTTP/|content-type|content-disposition)'
)
```

The frontend half of a deploy is only checked by loading the UI: the Master
Feed card must show an **Export OPML** button, and clicking it must download
`letterfeed.opml`. If the endpoint answers but the button is missing, the
frontend image is still upstream's.

The CSP, `X-Content-Type-Options` and `Referrer-Policy` values must exactly
equal the ones asserted in `backend/app/tests/test_routers.py`. If they're
missing or altered after the rewrite, roll back: don't leave an unsandboxed
entry page running.
