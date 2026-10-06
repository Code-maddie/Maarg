# SH-205 Backend

FastAPI service for **SH-205 — Intelligent Shipment Piggybacking**
(Predict → Price → Plan → Prove).

Deployment instructions live in the [root README](../README.md). This file
covers the service itself.

## Requirements

- Python 3.14

> `pydantic` must stay at **>= 2.12** on Python 3.14. Earlier releases have no
> `pydantic-core` cp314 wheel and fall back to a Rust build that fails without
> a full MSVC + cargo toolchain.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
cp .env.example .env        # defaults work for local development
```

`requirements.txt` is the production set; `requirements-dev.txt` adds pytest
and httpx.

## Run

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

| URL | Purpose |
| --- | --- |
| `/` | Service banner |
| `/health` | Liveness probe |
| `/ready` | Readiness probe, with per-dependency checks |
| `/docs` | Swagger UI |
| `/api/v1/…` | Every route, also mounted under the versioned prefix |
| `/ws/live` | WebSocket event stream |

A fresh database has no simulated world. Seed one with `POST /simulate/reset`.

## Test

```bash
.venv/Scripts/python.exe -m pytest           # full suite
.venv/Scripts/python.exe -m pytest -m "not slow"   # skip model-loading tests
```

## Layout

```
backend/
├── app/
│   ├── main.py              app factory, CORS, lifespan, router wiring
│   ├── api/v1/routes/       auth, fleet, health, hubs, map, market,
│   │                        model, realtime, shipments, simulation
│   ├── core/                config, database, logging, security, geo
│   ├── engines/             E1–E9, one package each
│   ├── models/              SQLAlchemy models
│   ├── schemas/             Pydantic request/response models
│   ├── services/            orchestration, booking, events, notifications
│   └── workers/             simulation clock and tick loop
├── alembic/                 migrations
├── artifacts/               E1 serving model (read-only, committed)
├── credentials/             gitignored; local Firebase service account
└── tests/                   unit and integration suite
```

## Configuration

Every setting comes from the environment or `backend/.env` — see
[.env.example](.env.example). Nothing outside `app/core/config.py` reads
`os.environ` directly.

| Concern | Local | Production |
| --- | --- | --- |
| Database | SQLite file | PostgreSQL via `DATABASE_URL` |
| Cache | In-process dict | In-process dict |
| Geo queries | Haversine helper | Haversine helper |
| Firebase | Service-account file | `FIREBASE_CREDENTIALS_JSON` env var |
| Auth | `AUTH_MODE=disabled` optional | `firebase`, enforced |

`DATABASE_URL` is the only thing that changes between the two. A
`postgres://` URL from the host is rewritten to the psycopg driver
automatically, so it can be pasted verbatim.

## Failure behaviour

Startup is deliberately tolerant: a missing E1 artifact or an unusable
Firebase credential is recorded and reported by `/ready`, rather than
preventing the service from starting. Liveness stays green so the platform
does not restart the process in a loop.

- No E1 artifact → `/model/status` reports `model_loaded: false`; prediction
  routes answer 503.
- No Firebase credential → protected routes answer 503 with the reason.

## Safety

- `backend/credentials/` and every `.env` are gitignored.
- Secrets never appear in logs or responses. `/auth/web-config` serves only
  the four public Firebase web-config fields, never service-account material.
- `AUTH_MODE=disabled` is refused when `ENVIRONMENT=production`.
