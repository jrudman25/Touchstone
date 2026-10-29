# Touchstone - LLM Evaluation Dashboard

A local-first dashboard for running a dataset through several prompt versions and models, then comparing which combination wins on quality, latency, and cost. It replaces eyeballing outputs in a notebook with repeatable runs, live progress, automatic scoring, and run-to-run regression detection.

## Status

Early development. The uv workspace, shared tooling, dev data stores, and CI workflow are in place. The Django records service is in place: its data model (users, organizations, memberships, projects, prompt templates with immutable versions, datasets, and provider, model, and scorer configs), migrations, admin, validation rules, JWT authentication (RS256 access tokens with a rotating refresh cookie), an organization-scoped REST API under `/api/records/` with an OpenAPI schema at `/api/records/schema/`, and a `seed_dev` command exist and are tested. A FastAPI service skeleton verifies those tokens and checks organization roles under `/api/eval/`. A Vue app skeleton handles sign-in, keeps the session across reloads, and lists your organizations and projects through typed API clients generated from both OpenAPI schemas. Runs, the worker, and the evaluation screens are not built yet. See [SPEC.md](SPEC.md) for the full specification.

## Planned features

- Prompt templates with immutable versions and `{{variables}}`
- JSONL dataset upload with optional expected outputs
- Runs across one or more models with live streamed progress
- Scoring by exact match, contains or regex, and LLM judge rubric, plus latency, token, and cost metrics
- Side-by-side run comparison that flags regressed rows
- Runs fully locally on free software, with a mock provider and local Ollama models

## Stack

Django and Django REST framework (PostgreSQL) for accounts and configuration, FastAPI for the run API and streaming, an arq worker on Redis for model calls and scoring, MongoDB for run output, and a Vue 3 + Vite + TypeScript frontend. During development Docker Compose runs only the data stores; the Python services run natively with uv, and a Compose `app` profile for one-command full-stack runs is planned.

## Prerequisites

- Python 3.13
- [uv](https://docs.astral.sh/uv/) 0.13.4 (`python -m pip install --user uv==0.13.4`, then invoke as `python -m uv` or use the installed `uv` shim)
- Docker Desktop with Compose for the data stores
- Node 24.11 or newer within the 24.x line (see `web/.nvmrc`) with npm, for the frontend

On Windows with Docker Desktop, capping the WSL2 VM at about 6 GB of memory in `%UserProfile%\.wslconfig` is recommended so the stores leave room for the rest of the stack. This is manual host configuration, not managed or verified by this repository.

## Setup

```sh
cp .env.example .env          # then edit the placeholder values
uv sync --all-packages --locked
uv run python scripts/generate_dev_keys.py   # creates .secrets/jwt/{private,public}.pem
docker compose up -d --wait                  # postgres, mongo, redis on 127.0.0.1
uv run --env-file .env python services/records/manage.py migrate
uv run --env-file .env python services/records/manage.py seed_dev
```

`seed_dev` creates a superuser from `DEV_SUPERUSER_USERNAME` and `DEV_SUPERUSER_PASSWORD` in `.env`, plus a `dev` organization, a demo project, and a mock provider and model. It is safe to run again and never changes an existing user's password.

Compose reads `.env` automatically; native commands load it explicitly with `uv run --env-file .env <command>`. Run commands from the repository root. Use `127.0.0.1` rather than `localhost` for store hosts (as in `.env.example`): the stores listen on IPv4 loopback only, and on Windows `localhost` can try IPv6 first and stall.

Start the records service and open the admin at `http://127.0.0.1:8000/api/records/admin/`:

```sh
uv run --env-file .env uvicorn records.asgi:application --port 8000
```

Sign in to the admin with the seeded superuser. Log in to the API with `POST /api/records/auth/token/`. It returns an access token to send as `Authorization: Bearer <token>`. The API schema is at `http://127.0.0.1:8000/api/records/schema/`.

In a second terminal, start the eval API (health check at `http://127.0.0.1:8001/health`):

```sh
uv run --env-file .env uvicorn eval_api.main:app --port 8001
```

In a third terminal, start the web app and open `http://localhost:5173`. Sign in with the seeded superuser. The Vite dev server proxies `/api/records` to Django and `/api/eval` to FastAPI, so the browser uses a single origin.

```sh
cd web
npm ci
npm run dev
```

## Checks

```sh
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run --env-file .env pytest   # records tests use the Compose Postgres (separate test database)
```

From `web/`:

```sh
npm run lint          # oxlint
npm run lint:vue      # ESLint, Vue template rules only
npm run typecheck     # vue-tsc
npm test              # Vitest
npm run generate:api  # re-export both OpenAPI schemas and regenerate src/api/generated/
```

The generated API types under `web/src/api/generated/` are committed. CI regenerates them and fails if they differ, so run `npm run generate:api` and commit the result after changing a Django or FastAPI endpoint.

## License

[MIT](LICENSE)
