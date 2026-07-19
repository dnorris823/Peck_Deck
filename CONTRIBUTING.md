# Contributing to Peck Deck

## Branch & PR flow

- `main` is the default branch and should always be green (CI passing).
- Do work on a short-lived feature branch, then open a pull request into `main`.
- Keep PRs focused — one logical change per PR where practical.
- CI (`.github/workflows/ci.yml`) runs on every push and PR to `main`. Get it green before merging.

## Running things locally

**Backend tests** (no Postgres required — the suite uses a throwaway SQLite DB):

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt
pytest -q
```

**Integration + contract tests** (real `postgres:16`, live in-process servers,
GPU mocked — one command brings up the DB, runs, and tears down):

```bash
pip install -r integration_tests/requirements.txt
bash scripts/run_integration.sh
```

Already have a Postgres you want to reuse? Export `PECK_TEST_DATABASE_URL`
(an asyncpg URL) and the script runs against it without touching docker.

**Backend + database** (full stack, from project root):

```bash
docker compose up --build
```

**Frontend** (from `frontend/`):

```bash
npm ci
npm run build      # production build (what CI checks)
npm run dev        # local dev server
```

## Recommended repository settings

Enable branch protection on `main` (repo **Settings → Branches → Add rule**):

- Require a pull request before merging.
- Require the **CI** status checks (`Backend tests`, `Integration + contract tests`, `Frontend build`) to pass.
- Optionally require branches to be up to date before merging.

This keeps the freshly-promoted `main` from regressing.

## Conventions

See `CLAUDE.md` for the project's architecture and coding conventions
(async everywhere, bcrypt passwords, images as `bytea`, secrets in env vars,
Litestar for the API vs. FastAPI for the inference server). The phased plan for
outstanding work lives in `FLEDGE_ROADMAP.md`.
