# LLM Evaluation Dashboard

A local-first dashboard for running a dataset through several prompt versions and models, then comparing which combination wins on quality, latency, and cost. It replaces eyeballing outputs in a notebook with repeatable runs, live progress, automatic scoring, and run-to-run regression detection.

## Status

In design. No code yet. See [SPEC.md](SPEC.md) for the full specification.

## Planned features

- Prompt templates with immutable versions and `{{variables}}`
- JSONL dataset upload with optional expected outputs
- Runs across one or more models with live streamed progress
- Scoring by exact match, contains or regex, and LLM judge rubric, plus latency, token, and cost metrics
- Side-by-side run comparison that flags regressed rows
- Runs fully locally on free software, with a mock provider and local Ollama models

## Stack

Django and Django REST framework (PostgreSQL) for accounts and configuration, FastAPI for the run API and streaming, an arq worker on Redis for model calls and scoring, MongoDB for run output, and a Vue 3 + Vite + TypeScript frontend. The whole backend is defined in Docker Compose.

## License

[MIT](LICENSE)
