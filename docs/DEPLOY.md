# Deploying MPLADS Sentinel

**Status: not deployed.** The build machine has no deployment CLI other than
GitHub's. The build agent may not create hosting accounts. GitHub Pages serves
static files only, and this app needs its Python API. What is here is
configuration and steps for a person with an account to follow. None of it has
been exercised.

The verified way to run the system is local: `demo.ps1` (see the README).

## What a deployment needs

| Part | Size measured locally | Notes |
|---|---|---|
| API process | about 330 MB memory after serving every page | Imports the ML stack for the simulator, counterfactuals and learning |
| API with uploads | add the sentence-transformer model, several hundred MB more | Only when the Data Ingest page scores a file |
| Database | 435 MB as SQLite | Postgres works through `DATABASE_URL` |
| Pipeline artefacts | `data/processed/`, `models/` | Produced by `python -m ml.train`; not in the repository |
| Dashboard | static files, about 1.5 MB | Needs `/api` routed to the API |

Free plans with 512 MB of memory are too small for the API. Plan for at least
1 GB, or 2 GB with uploads enabled.

## Option A: a single VM (simplest)

On any Linux VM with 2 GB of memory:

1. Clone the repository and run `python -m ml.train`, or copy
   `data/processed/` and `models/` from a machine that has run it.
2. `cp .env.example .env`, then set `JWT_SECRET`, `POSTGRES_PASSWORD` and
   `PRESENTATION_MODE=1`.
3. `docker compose up --build -d`
4. `docker compose exec api python -m backend.app.loader`
5. `docker compose exec api python -m backend.app.demo_seed --reset`
6. Put a TLS-terminating proxy in front of port 8080.

## Option B: Render (blueprint in `render.yaml`)

1. Create a Render account and connect this GitHub repository.
2. New, then Blueprint, and select `render.yaml`. This creates the API (Docker),
   the static dashboard and Postgres.
3. Upload `data/processed/` and `models/` to the API's persistent disk. Render's
   shell or `scp` both work.
4. Open a shell on the API service and run `python -m backend.app.loader`, then
   `python -m backend.app.demo_seed --reset`.
5. Check `/api/health` reports `"presentation_mode": true` before sharing the link.

## Before any public link

- `PRESENTATION_MODE=1`. The repository is public and so is the link; MP and
  vendor names must be pseudonyms and private names masked.
- A real `JWT_SECRET`. The app warns at startup when it runs on the development
  secret.
- Change or remove the demo accounts in `configs/api.yaml`. They all share the
  published password `demo123`.
- `SCHEDULER_ENABLED=0` unless the host can run the nightly pipeline, which wants
  a GPU and several GB of memory.
