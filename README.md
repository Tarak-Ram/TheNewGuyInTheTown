# The New Guy in Town

An AI helper for people moving to a new city. The first product is the AI Relocation Agent for IT employees moving to Hyderabad.

The repository holds the plan, the build prompts, and the working English-language app for Prompts 1 to 7: area advisor, voice call to PGs, comparison table, and agreement checker, joined into one guided flow.

**Want to see it work?** Follow [DEMO.md](DEMO.md). It runs with no Google keys in a clearly labelled demo mode.

## What is here

| Path | What it contains |
| --- | --- |
| `docs/PRD.md` | Full product requirements and roadmap |
| `docs/prompts/` | Prompts for your coding agent, one file each |
| `DEMO.md` | The three-minute demo script, the backup plan and the reset command |
| `apps/` | `web` (Next.js), `api` and `voice-gateway` and `worker` (FastAPI) |
| `packages/` | Shared contracts (`schemas`) and shared logic (`tools`) |
| `evals/` | Labelled test sets and scoring for fact extraction and agreement checking |
| `scripts/` | `seed.py`, `reset_demo.py`, `check_health.py` |
| `.env.example` | Environment variable names, without real values |

## Before you start

1. Check whether the Buildathon allows code written before 20 November 2026.
2. Install Git, Node.js, Python 3.11 or newer, and Docker Desktop.
3. Copy `.env.example` to `.env`, and add your own keys only to `.env`.

## How to build

```bash
git clone https://github.com/Tarak-Ram/TheNewGuyInTheTown.git
cd TheNewGuyInTheTown
code .
```

Open your coding agent in VS Code, then work one step at a time:

1. Start a new agent chat.
2. Paste `docs/prompts/prompt-00.md` and `docs/prompts/prompt-01.md`.
3. Run the app and tests, and read the main changes.
4. Commit the working result.
5. Start a new chat with `prompt-00.md` and the next prompt.

Think of Prompt 0 as the site rules given to every new worker. Each later prompt is that worker's job for the day.

## Run it locally

```bash
docker compose up -d --build        # db, api, voice-gateway, worker, web
python scripts/check_health.py      # waits until all four services are healthy
```

| Service | URL |
| --- | --- |
| Web | http://localhost:3000 |
| API | http://localhost:8010/health/ready |
| Voice gateway | http://localhost:8011/health/ready |
| Worker | http://localhost:8012/health/ready |
| Postgres | localhost:5433 |

First-time setup for the database and sign-in:

```bash
cp .env.example .env                # then fill in the values below
python scripts/seed.py              # 8 areas and 12 fake PGs (safe to run twice)
```

| `.env` name | How to get it |
| --- | --- |
| `PHONE_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SESSION_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID` | Google Cloud Console, OAuth client ID (Web). Add `http://localhost:3000` as an authorised origin |

Optional settings in `.env`:

| Name | What it does |
| --- | --- |
| `DEMO_MODE=true` | Demo sign-in, 7 known offices, and commute **estimates** labelled as demo data. Only while `MAPS_API_KEY` is empty. Never set it in staging or production. |
| `MAPS_API_KEY` | Optional. If set, address check and commute times use Google (Places and Routes APIs). If empty, and demo mode is off, the free OpenStreetMap providers are used (Nominatim and OSRM, no key). Their commute times have a peak-hour allowance and no live traffic, and the screen says so. |
| `GOOGLE_API_KEY`, `GEMINI_LIVE_MODEL` | The live voice call |
| `GEMINI_TEXT_MODEL` | AI-written area explanations, fact extraction, and agreement review. Without it the app uses safe built-in fallbacks. |

Host ports can be changed with `API_PORT`, `GATEWAY_PORT`, `WORKER_PORT` and `DB_PORT`.

```bash
# One-time Python setup
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Windows
# Lint and tests (the tests need the database: docker compose up -d db)
ruff check . && pytest
cd apps/web && npm ci && npm run lint && npm test

# Quality checks on the labelled test sets
python evals/extraction_eval.py     # call facts
python evals/agreement_eval.py      # agreement risks
```

## Do not run these yet

- `prompt-09.md`: real phone calls need the compliance gate in the PRD to be complete.
- `prompt-11.md`: use it only after the Buildathon demo and the earlier roadmap phase pass.
