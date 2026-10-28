# Touchstone - LLM Evaluation Dashboard

A local-first dashboard for running a dataset through several prompt versions and models, then comparing which combination wins on quality, latency, and cost. It replaces eyeballing outputs in a notebook with repeatable runs, live progress, automatic scoring, and run-to-run regression detection.

## Status

Checkpoint A (foundations) complete: the uv workspace, shared tooling, dev data stores, and CI workflow are in place and verified. The Django, FastAPI, worker, and Vue applications are not built yet; the service packages are empty scaffolds. See [SPEC.md](SPEC.md) for the full specification.

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
- Node 24 (needed later for the frontend; not required yet)

On Windows with Docker Desktop, capping the WSL2 VM at about 6 GB of memory in `%UserProfile%\.wslconfig` is recommended so the stores leave room for the rest of the stack. This is manual host configuration, not managed or verified by this repository.

## Setup

```sh
cp .env.example .env          # then edit the placeholder values
uv sync --all-packages --locked
uv run python scripts/generate_dev_keys.py   # creates .secrets/jwt/{private,public}.pem
docker compose up -d --wait                  # postgres, mongo, redis on 127.0.0.1
```

Compose reads `.env` automatically; native commands load it explicitly with `uv run --env-file .env <command>`.

## Checks

```sh
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## License

[MIT](LICENSE)
