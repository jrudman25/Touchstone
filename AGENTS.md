# AGENTS.md

Guidance for coding agents working on the LLM Evaluation Dashboard. `SPEC.md` is the source of truth for product behavior, data shapes, and endpoints. Read the relevant section before changing anything it covers, and update `SPEC.md` in the same change if behavior intentionally diverges.

## Status

Checkpoint A (workspace and tooling) is done: the uv workspace with the `evalcore`, `records`, `eval-api`, and `eval-worker` packages, the Compose dev stores (`postgres`, `mongo`, `redis`), the dev JWT key generator, and the CI workflow exist and pass their gates. No application code exists yet; the packages are empty scaffolds, and `web/` does not exist. The layout below remains the agreed target for what is not built yet. `TODO.md` is the owner's private task list and is git-excluded; do not reference it from committed files.

## Git workflow

- **Agents never commit, push, or create branches.** Leave all changes uncommitted for the owner to review and commit.
- Because each phase lands as one uncommitted diff, stop at natural checkpoints within a phase and summarize what changed so the owner can review and commit before you continue.

## Architecture rules

Each component has one job. Do not move responsibilities across these lines without updating `SPEC.md`.

| Component | Owns | Never does |
| --- | --- | --- |
| Django + DRF (PostgreSQL) | Users, organizations, memberships, projects, prompt templates and versions, dataset metadata, provider/model/scorer configs, admin, JWT signing | Store runs, results, or dataset rows |
| FastAPI | Run API, SSE stream, results paging, compare aggregation, JSONL upload into Mongo, playground | Sign JWTs, write relational records |
| Worker (arq on Redis) | Rendering prompts, calling providers, scoring, writing results, publishing run events, recomputing run summary | Serve HTTP (health is arq's Redis health check) |
| MongoDB | `runs`, `results`, `dataset_rows` | |
| Vue SPA | All UI | Hold tokens anywhere but memory (access) and httpOnly cookie (refresh) |

Invariants:

- **Auth:** Django signs RS256 JWTs with `djangorestframework-simplejwt`. Claims include the user id and an `{org_id: role}` map (JSON keys are strings; verifiers convert them to integers). The refresh view rebuilds the role map from the database, never copies it from the old token. Rotated and logged-out refresh tokens are blacklisted. Bearer credentials are access tokens only: the shared `evalcore` verifier requires a present, unexpired `exp`, a valid `user_id`, the role map, and `token_type` exactly `access`, and rejects a refresh token or a missing token type even when correctly signed; DRF bearer auth is access-only too. FastAPI and the worker only ever hold the public key; `records` holds both the private key and the public key (simplejwt's RS256 `VERIFYING_KEY`). Every FastAPI route checks the role with a dependency: `viewer` reads, `editor` creates and cancels runs, `owner` is a superset of `editor`.
- **Tenant isolation:** every query is scoped to an organization the caller belongs to. Never return a run, result, or dataset row without checking the caller's role on its organization. Writes validate that every referenced object (project, provider, model, scorer, judge model) belongs to the same organization. Run documents store `organization_id` so FastAPI authorizes from the token alone.
- **Django is the only writer of relational records.** When FastAPI needs Django data (or must update a Django field such as `Dataset.row_count`), it calls DRF with the caller's own JWT. No service-to-service secret.
- **Prompt versions are immutable.** Editing creates `number + 1`; every persisted `PromptVersion` field is creation-only across the ORM, admin, and API paths — model `save`/`delete` and queryset `update`/`bulk_update`/`delete` reject changes to existing rows, saved versions are view-only in admin, and the API is create/read only. `PromptVersion.template` uses `on_delete=PROTECT` so template, project, or organization deletion cannot cascade away versions. `(template, number)` is unique; number allocation runs in `transaction.atomic` with a lock on the parent template row.
- **Runs snapshot their inputs.** At `POST /runs` the API builds a frozen snapshot — prompt, model (including tag and digest when the provider reports one), scorer settings, `context_length`, and each judge model's full config — fetching provider metadata through the shared `evalcore` client. The worker reads the snapshot, never live Django config or provider metadata calls.
- **Idempotent writes.** `results` has a unique index on `(run_id, model_config_id, row_index)`. Use upserts so any lifecycle step can be retried safely.
- **One run, one model at a time.** The worker runs a single run job at a time (arq `max_jobs=1`) and one model at a time within it, honoring each provider's `max_concurrency` (1 for Ollama) and `requests_per_minute`, with backoff on rate limits.
- **Run events go through Redis Streams.** The worker appends to `run:{id}:events`; FastAPI serves SSE from it with stream entry ids as event ids, so clients resume with `Last-Event-ID` while the capped history is retained. When history is trimmed or expired, FastAPI sends a `reset` event and the SPA refetches authoritative state through the run/results APIs (see `SPEC.md` > Run lifecycle). Do not use Mongo change streams (no replica set).
- **Mock provider** is an in-process `evalcore` client with the same interface as real providers, deterministic via a seed, with no `base_url`.
- **Cancellation** is a Redis flag checked between rows. Partial results are kept.
- **Same origin, no CORS:** the browser only talks to one origin. Vite (development) or Caddy (`app` profile) proxies `/api/records/*` to Django and `/api/eval/*` to FastAPI without rewriting paths; each service mounts its own prefix. Django admin and its static files live under `/api/records/` too, so they are reachable through the proxy. Do not add CORS middleware. Unprefixed `/health` routes are not proxied.
- **Stream auth:** the SPA reads SSE with `fetch` (not `EventSource`) so it can send the `Authorization` header. Proxies must not buffer SSE responses.
- **Refresh cookie:** `HttpOnly`, `SameSite=Strict`, `Secure` from an environment variable, `Path` scoped to the Django auth endpoints; the refresh endpoint requires a custom request header. DRF API views use JWT authentication only, never `SessionAuthentication`.
- **Service-to-service URLs:** FastAPI reaches Django via `RECORDS_BASE_URL`, never through the browser-facing proxy.
- **Logging:** every log line in FastAPI and the worker carries the `run_id` when one exists. Every HTTP service (Django, FastAPI) exposes `GET /health`; the worker's health is arq's built-in Redis health check (`arq --check`), used as its Compose healthcheck.
- **Secrets:** hosted provider keys and the JWT private key come from environment variables or mounted files, never committed. `ProviderConfig.api_key_env` stores only the variable *name*. Keep a `.env.example` with placeholder values only.
- **Context truncation is a correctness bug.** Ollama truncates over-long prompts silently. Record `context_length` in the run snapshot and set `context_limited` on affected results (see `SPEC.md` > Context length).

## Local environment and resource limits

The target machine is a 16 GB RAM desktop (i7-7700K, GTX 1080 8 GB VRAM) that must also run Ollama, an IDE, and a browser. Keep the stack free to run and lean:

- **Machines:** development happens on the desktop or a GPU-less laptop (both Windows, identical setup, synced through git). Real evals run only on the desktop. Nothing may depend on cross-machine networking; the laptop uses only the mock provider.
- **Ollama runs natively** on the desktop, bound to `127.0.0.1`, never in Compose. Pascal cards need NVIDIA driver 570+; pin the Ollama version and disable auto-update. Record the tested Ollama version here once verified.
- **Development:** Compose runs only `postgres`, `mongo`, `redis`. Django, FastAPI, and the worker run natively with `uv`; the SPA runs on the Vite dev server. App services live behind the Compose `app` profile for full-stack runs.
- **Ports:** Vite `5173`, Django `8000`, FastAPI `8001`, Caddy published on `8080`. Store ports are published bound to `127.0.0.1` only, never `0.0.0.0`.
- **Memory:** every Compose service has a memory limit; MongoDB runs with `--wiredTigerCacheSizeGB 0.5`; the Docker Desktop VM is capped at about 6 GB via `.wslconfig`.
- **Provider URLs:** Ollama is `http://localhost:11434` from native services and `http://host.docker.internal:11434` from containers.
- **No paid services.** Do not add dependencies or infrastructure that require a paid account. Remote GPU machines are reached as providers over a private network (for example Tailscale), never by exposing Ollama publicly.

## Target repository layout

```
pyproject.toml            uv workspace root (members below), shared dev tooling config
uv.lock
.python-version          3.13
docker-compose.yml        postgres, mongo, redis; records, api, worker, proxy under the "app" profile
.env.example
.github/workflows/ci.yml  lint, types, and tests on every push and pull request
proxy/Caddyfile           same-origin proxy and SPA static files for the "app" profile
proxy/Dockerfile          multi-stage: builds web/ with Node, then serves dist/ from Caddy
scripts/                  cross-platform Python helper scripts (dev JWT keypair, OpenAPI schema export)
services/
  records/                Django + DRF project (named "records" to avoid shadowing the django package)
  records/Dockerfile      each service Dockerfile builds from the repo root (uv workspace context)
  api/                    FastAPI app (+ Dockerfile)
  worker/                 arq worker (+ Dockerfile)
packages/
  evalcore/               Shared Python: Pydantic schemas, Mongo access, JWT verification,
                          provider clients, scorers, prompt rendering
web/                      Vue 3 + Vite + TypeScript SPA
  src/api/generated/      committed openapi-typescript output for both schemas
```

Shared logic used by both FastAPI and the worker (schemas, providers, scorers, Mongo helpers, JWT verification) lives in `packages/evalcore`, not duplicated in each service.

## Tooling decisions

- **Python:** uv workspace with one lockfile. Use `uv add --package <member> <dep>` to add dependencies to a specific member. Pin the Python version in `.python-version`.
- **Node:** npm, with `web/package-lock.json` committed. Pin Node 24 (LTS) in `web/.nvmrc` and `engines`; move to a newer LTS only deliberately.
- **Platform:** development machines are Windows; CI is Linux. Write helper scripts in Python or as npm scripts, never `.ps1` or `.sh`.
- **API clients:** `openapi-typescript` generates types from the Django (`drf-spectacular`) and FastAPI schemas; call them with `openapi-fetch`. Do not hand-write API response types. Schemas are exported without running servers (`manage.py spectacular --file` and a script that dumps FastAPI's `app.openapi()`), the generated types are committed, and CI regenerates them and fails on any diff.
- **Job queue:** arq, pinned. It is in maintenance-only mode upstream, so keep all enqueueing behind one function in `evalcore` to allow a later swap.
- **MongoDB driver:** PyMongo's async API (`AsyncMongoClient`). Motor is deprecated; do not add it.
- **Django OpenAPI:** `drf-spectacular`, so the SPA can generate typed clients from both Django and FastAPI schemas.
- **Django static files:** WhiteNoise (approved) serves admin static files in containers. Django's ASGI app runs under uvicorn in containers; no gunicorn.
- **Django user model:** a custom user model (subclass of `AbstractUser`) exists from the first migration, so it can be extended later without a migration reset.
- **Frontend libraries:** Vue Router, Pinia, TanStack Query and TanStack Table for Vue, Chart.js. Do not add a component library without asking.
- **Testing:** pytest (with `pytest-django` for `records`, `httpx` for FastAPI), Vitest for `web`. Do not add Playwright or Cypress without approval.
- **Lint and types:** ruff and mypy for Python; ESLint and `vue-tsc` for `web`.
- **Container images:** pin explicit version tags in `docker-compose.yml` and every Dockerfile `FROM`, never `latest`.
- **New dependencies:** prefer versions published at least 7 days ago; no floating ranges.

## Testing conventions

- Use the mock provider for all automated tests. Tests must never require Ollama, a GPU, or network access to hosted providers.
- Run Mongo, Postgres, and Redis-backed tests against real stores, never mocks of our own stores or modules: locally the Compose services with separate test database names, in CI GitHub Actions service containers.
- CI (`.github/workflows/ci.yml`) runs ruff, mypy, pytest, ESLint, `vue-tsc`, and Vitest. Keep it green; the repo is public. Only change CI as part of a requested task (for example adding steps for new code), and call out every CI change in your summary.
- Cover tenant isolation and role checks for every new endpoint (viewer denied writes, other organization denied reads, writes referencing another organization's objects rejected).

## Commands

Verified on Windows (Git Bash) with system Python 3.13.5. `uv` is pinned at 0.13.4 and installed user-local (`py -3.13 -m pip install --user uv==0.13.4`); `python -m uv` works without any PATH change, and the `uv`/`uvx` shims work once the user Scripts directory is on PATH. Substitute `uv` for `python -m uv` when the shim is available.

- **Sync the workspace** (creates `.venv`, builds all four members): `python -m uv sync --all-packages --locked`
- **Lockfile**: regenerate with `python -m uv lock`, verify freshness with `python -m uv lock --check`
- **Lint**: `python -m uv run ruff check .` and `python -m uv run ruff format --check .` (fix with `ruff check --fix` / `ruff format`)
- **Types**: `python -m uv run mypy .`
- **Tests**: `python -m uv run pytest` (only `scripts/tests` exists so far; per-service tests come with Checkpoint B)
- **Dev JWT keypair**: `python -m uv run python scripts/generate_dev_keys.py` writes `.secrets/jwt/private.pem` and `public.pem`, and refuses to overwrite existing files
- **Data stores**: `cp .env.example .env`, fill in the placeholders, then `docker compose up -d --wait`. Check with `docker compose ps`. Postgres, Mongo, and Redis are published on `127.0.0.1` ports 5432, 27017, and 6379.
- **Environment**: Compose reads `.env` automatically; native commands load it explicitly with `python -m uv run --env-file .env <command>`. There is no dotenv dependency.
