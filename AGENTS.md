# AGENTS.md

Guidance for coding agents working on the LLM Evaluation Dashboard. `SPEC.md` is the source of truth for product behavior, data shapes, and endpoints. Read the relevant section before changing anything it covers, and update `SPEC.md` in the same change if behavior intentionally diverges.

## Status

Checkpoint A (workspace and tooling) is done: the uv workspace with the `evalcore`, `records`, `eval-api`, and `eval-worker` packages, the Compose dev stores (`postgres`, `mongo`, `redis`), the dev JWT key generator, and the CI workflow exist and pass their gates.

Checkpoint B (Django `records` service and `evalcore` JWT verifier) is done. Verified: the `records` Django project (environment-only settings, `/health`, admin at `/api/records/admin/`, WhiteNoise static under `/api/records/static/`), the apps `accounts` (custom `User`, `Organization`, `Membership`), `projects` (`Project`, `PromptTemplate`, `PromptVersion`, `Dataset`), and `providers` (`ProviderConfig`, `ModelConfig`, `ScorerConfig`) with initial migrations and admin, and model-level rules (prompt-version immutability and `create_prompt_version`, tenant-move and reference checks in each model's `clean()`, scorer params, provider `base_url`, `baseline_run_id`), RS256 simplejwt auth with cookie-based obtain, refresh, and logout views plus `GET /api/records/auth/me/`, the `evalcore.access_tokens` verifier, the DRF API for every record under `/api/records/` (see "Records API conventions" below), the drf-spectacular schema at `/api/records/schema/` and its offline export, and the `seed_dev` command. The last-owner rule is enforced on the API and in Django admin (`records/accounts/ownership.py`; see "Model validation lives in `clean()`" below). Not built yet: the Phase 2 set-row-count action.

Checkpoint C (FastAPI skeleton, Vue SPA skeleton, generated API types) is done. Verified: `eval_api` (`create_app` factory in `eval_api/main.py`, unprefixed `GET /health`, `GET /api/eval/me`, settings read from `JWT_PUBLIC_KEY_PATH` at startup in the lifespan so `create_app().openapi()` needs no environment, `get_claims` bearer dependency returning 401 with `WWW-Authenticate: Bearer`, `require_org_role(minimum)` reading `organization_id` from the route and returning 403), shared run-id logging in `evalcore.run_logging` (`configure_logging`, `run_id_var`), `scripts/export_openapi.py`, and `web/` (Vite proxy, openapi-fetch clients in `src/api/clients.ts`, `authFetch` with one shared refresh and one retry on 401, Pinia auth store with the access token in memory only and one refresh on app start, router guard, login and home views, Vitest tests, oxlint plus ESLint). CI has `web` and `api-types` jobs. `eval-worker` is still an empty scaffold; Mongo, Redis, runs, and the `app` profile are Phase 2 and later. The layout below remains the agreed target for what is not built yet. `TODO.md` is the owner's private task list and is git-excluded; do not reference it from committed files.

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
- **Pinned service versions:** Django 6.1.2, Django REST framework 3.18.3, djangorestframework-simplejwt 5.5.1, drf-spectacular 0.30.0, PyJWT 2.15.1, pydantic 2.14.1, FastAPI 0.159.1, uvicorn 0.54.0 (records and eval-api share the pin); type stubs django-stubs 6.1.2 and djangorestframework-stubs 3.18.1 must move with Django and DRF.
- **Pinned web versions:** Vue 3.5.44, Vue Router 5.4.0, Pinia 4.1.0, Vite 8.3.5, Vitest 4.1.12, openapi-fetch 0.17.0, openapi-typescript 7.13.0, oxlint and eslint-plugin-oxlint 1.89.0 (keep them equal), ESLint 10.13.0, eslint-plugin-vue 10.11.1. TypeScript stays on 5.9.3 because `@typescript-eslint/parser` 8.x and `openapi-typescript` 7.x do not support 6 or later. `engines` requires Node 24.11 or newer because Vue Router 5's dependencies need it.
- **Web auth client:** typed clients live in `web/src/api/clients.ts`: `recordsClient` and `evalClient` use `authFetch`, and `publicRecordsClient` handles login, refresh, and logout. Never add bearer or refresh handling anywhere else. The access token lives only in the Pinia store (`web/src/stores/auth.ts`). Router redirects go through `safeRedirect`, which accepts only same-origin absolute paths.
- **Model validation lives in `clean()`:** tenant-move, reference-consistency, and per-kind rules are implemented in each model's `clean()` (helpers in `records/tenancy.py`), so admin ModelForms apply them; DRF serializers must call the model's `clean()` rather than reimplementing the checks. Prompt versions are created only through `records.projects.services.create_prompt_version`. The last-owner rule lives in `records.accounts.ownership`:
  - `Membership.clean()` rejects demoting the last owner.
  - The membership API repeats the locked check inside its own transaction.
  - `MembershipAdmin` and `RecordsUserAdmin` list orphaning deletes as protected in `get_deleted_objects`, and re-check in `delete_model` and `delete_queryset`.
  - Deleting an organization still cascades its memberships.
  - Any new path that deletes or re-roles memberships, or deletes users, must use these helpers.
- **Auth wire contract (implemented):** endpoints `POST /api/records/auth/token/` (body `{username, password}`, returns `{access}`), `POST /api/records/auth/token/refresh/` (requires header `X-Auth-Refresh: 1`, else 403), `POST /api/records/auth/logout/` (204), and `GET /api/records/auth/me/`. The refresh token lives only in the `touchstone_refresh` cookie with `Path=/api/records/auth/`. The role map claim is `orgs` (`{"<org_id>": "owner" | "editor" | "viewer"}`), rebuilt from `Membership` rows on every mint (`records/accounts/auth/tokens.py`). simplejwt emits `user_id` as a JSON string; `evalcore.verify_access_token` accepts a positive int or an ASCII-digit string and returns an `AccessClaims` model with integer `user_id` and integer `orgs` keys. Do not use simplejwt's stock obtain or refresh views.
- **Records API conventions (implemented):** a DefaultRouter in `records/api/urls.py` serves `organizations`, `memberships`, `projects`, `prompt-templates`, `prompt-versions`, `datasets`, `providers`, `models`, and `scorers`. Viewsets subclass `records.api.viewsets.OrganizationScopedViewSet` and declare `organization_lookup` (the ORM path to `Organization`), `write_roles`, and `filter_params`. Querysets are filtered to the caller's memberships, so rows in other organizations return 404. Related fields use `MemberScopedPrimaryKeyRelatedField`, so a pk outside the caller's organizations is a 400 "does not exist". Roles are read from `Membership` rows, not token claims. Order of checks: field validation (400), then the role check on the target organization (403, before payload validation on detail routes), then model `full_clean()` through `records.api.validation.ModelCleanMixin` (400). Writes need `editor` or `owner`. Organization updates and all membership writes need `owner`. Organizations have no create or delete (405), and prompt versions have no update or delete (405). Deleting a row that `PROTECT` blocks returns 409. Filters must be integers (otherwise 400). Pagination is page-number based: 50 per page, `?page_size=` up to 200.
- **Frontend libraries:** Vue Router, Pinia, TanStack Query and TanStack Table for Vue, Chart.js. Do not add a component library without asking.
- **Testing:** pytest (with `pytest-django` for `records`, `httpx` for FastAPI), Vitest for `web`. Do not add Playwright or Cypress without approval.
- **Lint and types:** ruff and mypy for Python. For `web`, there are three tools:
  - oxlint is the primary linter for all JS/TS, including `.vue` `<script>` blocks. It is the fast local lint (`npm run lint`) and also runs in CI.
  - ESLint runs only `eslint-plugin-vue`, for `<template>` rules that oxlint cannot see. `eslint-plugin-oxlint` comes last in the ESLint config and is built from `.oxlintrc.json` (`buildFromOxlintConfigFile`), so ESLint never repeats a rule oxlint already covers. Do not add `typescript-eslint` type-aware rules or other overlapping plugins to ESLint. ESLint runs in CI and in the editor; a local full run is optional.
  - `vue-tsc` type-checks everything, template expressions included, locally and in CI.
- **Container images:** pin explicit version tags in `docker-compose.yml` and every Dockerfile `FROM`, never `latest`.
- **MongoDB stays on 7.0 (`mongo:7.0.43`) in both Compose and CI.** MongoDB 8.x either refuses to start or crashes on Linux kernels 6.19 and newer (SERVER-121912). GitHub's Ubuntu runners use kernel 7.0.x, and 8.0's exemption for kernel 7.0.14+ misreads Ubuntu kernel strings (SERVER-136848). Move to 8.x only after confirming it starts on the CI runner kernel and on Docker Desktop's WSL kernel, and keep Compose and CI on the same version.
- **New dependencies:** prefer versions published at least 7 days ago; no floating ranges.

## Testing conventions

- Use the mock provider for all automated tests. Tests must never require Ollama, a GPU, or network access to hosted providers.
- Run Mongo, Postgres, and Redis-backed tests against real stores, never mocks of our own stores or modules: locally the Compose services with separate test database names, in CI GitHub Actions service containers.
- CI (`.github/workflows/ci.yml`) runs ruff, mypy, pytest, oxlint, ESLint (template rules only), `vue-tsc`, and Vitest. Keep it green; the repo is public. Only change CI as part of a requested task (for example adding steps for new code), and call out every CI change in your summary.
- Cover tenant isolation and role checks for every new endpoint (viewer denied writes, other organization denied reads, writes referencing another organization's objects rejected).

## Commands

Verified on Windows (Git Bash) with system Python 3.13.5. `uv` is pinned at 0.13.4 and installed user-local (`py -3.13 -m pip install --user uv==0.13.4`); `python -m uv` works without any PATH change, and the `uv`/`uvx` shims work once the user Scripts directory is on PATH. Substitute `uv` for `python -m uv` when the shim is available.

- **Sync the workspace** (creates `.venv`, builds all four members): `python -m uv sync --all-packages --locked`
- **Lockfile**: regenerate with `python -m uv lock`, verify freshness with `python -m uv lock --check`
- **Lint**: `python -m uv run ruff check .` and `python -m uv run ruff format --check .` (fix with `ruff check --fix` / `ruff format`)
- **Types**: `python -m uv run mypy .`
- **Tests**: `python -m uv run --env-file .env pytest`. The `records` tests need the Compose Postgres; pytest-django creates and drops a separate `test_<POSTGRES_DB>` database. Test settings (`services/records/tests/records_test_settings.py`) generate throwaway RSA keys and never read `.secrets`. pytest runs with `--import-mode=importlib`; the mypy Django plugin also loads these test settings, so `mypy .` needs no `.env`.
- **Django management** (run from the repo root; relative `JWT_*_KEY_PATH` values resolve against the working directory): `python -m uv run --env-file .env python services/records/manage.py <command>`, for example `migrate` or `makemigrations --check --dry-run`.
- **Seed dev records**: `python -m uv run --env-file .env python services/records/manage.py seed_dev`. Reads `DEV_SUPERUSER_USERNAME` and `DEV_SUPERUSER_PASSWORD` and refuses to run if either is empty. Creates the superuser, the `dev` organization with an owner membership, "Demo project", the "Mock" provider, and the `mock-echo` model. Safe to rerun: it never changes an existing user's password.
- **OpenAPI schema export** (no server, no `.env`, no real keys): `python -m uv run python scripts/export_openapi.py` writes `.artifacts/openapi/eval.json` (in-process `create_app().openapi()`) and `.artifacts/openapi/records.json` (`manage.py spectacular --validate --fail-on-warn` under `records_test_settings`, which generates throwaway keys). It must produce no warnings. The live records schema is at `GET /api/records/schema/` (public, JSON).
- **Generated API types**: from `web/`, `npm run generate:api` runs the export and then `openapi-typescript` into `web/src/api/generated/records.ts` and `eval.ts`. Commit the generated files. CI's `api-types` job regenerates them and fails on any diff or untracked file. Regenerate whenever a Django serializer or view, or a FastAPI route or model, changes.
- **Run FastAPI natively**: `python -m uv run --env-file .env uvicorn eval_api.main:app --port 8001`, then check `http://127.0.0.1:8001/health`. A missing or unreadable `JWT_PUBLIC_KEY_PATH` stops startup with `SettingsError`.
- **Web** (from `web/`, Node 24.11 or newer): `npm ci`, then `npm run dev` (Vite on 5173; proxies `/api/records` to 127.0.0.1:8000 and `/api/eval` to 127.0.0.1:8001 without rewriting paths). Checks: `npm run lint` (oxlint), `npm run lint:vue` (ESLint, template rules only), `npm run typecheck` (vue-tsc), `npm test` (Vitest, happy-dom), `npm run build`. The full local stack is Django on 8000, FastAPI on 8001, and Vite on 5173; open `http://localhost:5173`.
- **Run Django natively**: `python -m uv run --env-file .env uvicorn records.asgi:application --port 8000`, then check `http://127.0.0.1:8000/health` and `http://127.0.0.1:8000/api/records/admin/`.
- **Use `127.0.0.1`, not `localhost`, for the stores**: on the Windows desktop, `localhost` resolves to `::1` first, and because the Compose ports are bound to `127.0.0.1` only, each new Postgres connection stalled about 60 seconds before falling back to IPv4 (measured; `127.0.0.1` connects in milliseconds). `.env.example` uses `127.0.0.1` for Postgres, Mongo, Redis, and `RECORDS_BASE_URL`.
- **Dev JWT keypair**: `python -m uv run python scripts/generate_dev_keys.py` writes `.secrets/jwt/private.pem` and `public.pem`, and refuses to overwrite existing files
- **Data stores**: `cp .env.example .env`, fill in the placeholders, then `docker compose up -d --wait`. Check with `docker compose ps`. Postgres, Mongo, and Redis are published on `127.0.0.1` ports 5432, 27017, and 6379.
- **Environment**: Compose reads `.env` automatically; native commands load it explicitly with `python -m uv run --env-file .env <command>`. There is no dotenv dependency.
