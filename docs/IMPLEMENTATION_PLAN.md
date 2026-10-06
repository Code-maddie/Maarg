# SH-205 — Implementation Plan

Source of truth: `SH.docx` (SH-205 Full Prototype Build Document).
Execution rule: implement → test → document in `srihitha.md` → continue.
Stop only at critical checkpoints: **3, 7, 13, 16, 19, 21, 23**.

---

## 0. Binding environment constraints

These override any conflicting guidance in `SH.docx` or `Implementation.md`.

| # | Constraint | Consequence |
|---|---|---|
| C1 | **No Docker. No docker-compose.** Not installed, not wanted. | No `Dockerfile`, no container-based infrastructure anywhere in the project. Removed from Phase 1 output on 2026-09-19. |
| C2 | Everything runs directly on the local machine. | Backend: `uvicorn app.main:app --reload`. Frontend: served as static files (it is a plain HTML/JS site — there is no `npm run dev` because there is no `package.json`; see C6). |
| C3 | **Database: SQLite**, not PostgreSQL/PostGIS. | Ships with Python; no server, no service. Accessed only through SQLAlchemy so `DATABASE_URL` can later point at a natively installed PostgreSQL with no code change. |
| C4 | **No Redis.** | E7 Graph Memory uses an in-process cache behind a narrow interface (`get/set/delete`), so Redis can be dropped in later without touching engine logic. |
| C5 | Firebase stays externally connected. | Uses the existing `frontend/.env` and `backend/credentials/firebase-credentials.json`. Credentials are never printed, copied, or modified. |
| C6 | Frontend is **not** React/Vite. | It is a static site at `frontend/sidecar-site/` (plain HTML + vanilla JS + Leaflet/Google Maps). `SH.docx` specifies React; the existing site is authoritative and **must not be rewritten**. |
| C7 | Python 3.14 is the only interpreter. | `pydantic >= 2.12` required (no cp314 wheel below that). ML dependency compatibility must be verified in Phase 3. |

### What C3/C4 cost us, honestly

- **PostGIS `ST_DWithin`** geo-pruning in E6 → replaced by a haversine helper. At prototype scale (30 hubs, 200 vehicles, 5 000 shipments) the difference is immaterial.
- **Redis sub-ms cache** for E7 labels → replaced by an in-process dict. Single-process prototype, so there is nothing to share across workers.
- **Concurrent writes.** SQLite serialises writers. Fine for a single-process demo; would not be fine in production.

None of these block any demo beat in `SH.docx` §15.

---

## 1. Target architecture (as actually built)

```
frontend/sidecar-site/  (static HTML/JS, Leaflet + Google Maps)
          |  HTTP + WebSocket
          v
backend/  FastAPI  (uvicorn, single process)
          |
          +-- app/api/v1/          REST + /ws/live
          +-- app/engines/e1..e9/  decision engines
          +-- app/services/        orchestration
          +-- app/workers/         simulation tick loop
          |
          v
    SQLite (sh205.db)  +  in-process cache  +  Firebase (Auth/Firestore, external)
```

Colab remains training-only. The backend loads exported E1 artifacts from
`e1-model/softHack/artifacts/` and never retrains.

---

## 2. Phase index

| Phase | Name | Critical | Status |
|---|---|---|---|
| 1 | Backend foundation | | ✅ done |
| 2 | Database foundation | | ✅ done |
| 3 | E1 integration | ⛔ | ✅ done — manual tests passed |
| 4 | Simulator | | ✅ done |
| 5 | E4 Adaptive Recovery Temperature | | ✅ done |
| 6 | Recovery Pressure Score | | ✅ done |
| 7 | E6 Piggy Router | ⛔ | ✅ done — manual tests passed |
| 8 | E7 Graph Memory | | ✅ done |
| 9 | E5 Bounty Market | | ✅ done |
| 10 | E2 Foresight Reservation | | ✅ done |
| 11 | E3 Hub Emergence | | ✅ done |
| 12 | Route Fusion | | ✅ done |
| 13 | Recovery Cascade | ⛔ | ✅ done — manual tests passed |
| 14 | E8 Explainer | | ✅ done |
| 15 | E9 Outcome Learning | | ✅ done |
| 16 | Recovery Orchestrator | ⛔ | ✅ done — manual tests passed |
| 17 | REST API | | ✅ done |
| 18 | WebSocket / realtime | | ✅ done |
| 19 | Firebase integration | ⛔ | ✅ done — valid-token round trip awaits owner |
| 20 | Google Maps integration | | ✅ done |
| 21 | Frontend integration | ⛔ | in progress |
| 22 | Metrics | | |
| 23 | End-to-end demo | ⛔ | |
| 24 | Hardening | | |
| 25 | Final documentation | | |

---

## PHASE 1 — Backend foundation ✅

**Objective.** A FastAPI service that starts, answers health probes and allows
the frontend origin through CORS.

**Delivered.** `app/main.py` (app factory, CORS, lifespan), `app/core/config.py`
(env-driven `Settings`), `app/core/logging.py` (unified text/JSON logging),
`app/api/v1/routes/health.py` (`/health`, `/ready`), `app/schemas/health.py`,
engine package placeholders `e1_misplacement`…`e9_learning`, `requirements.txt`,
`.env.example`, root `.gitignore`, 16 tests.

**Acceptance criteria — met.** Backend starts; `/health` returns 200; no
frontend changes required; 16/16 tests pass.

**Amended 2026-09-19 (constraint C1).** `backend/Dockerfile` and
`backend/.dockerignore` removed. They were optional deployment artifacts and
formed no part of the Phase 1 acceptance criteria; the service still starts and
all tests still pass without them.

---

## PHASE 2 — Database foundation

**Objective.** A persistent relational schema covering every entity the engines
need, with migrations, a session lifecycle, and working CRUD + geo queries.

**Why this phase exists.** Every later phase reads and writes this schema. The
simulator (4) populates it; the engines (5–15) query it; the API (17) exposes
it. Getting entity shape wrong here is expensive to fix later.

**Preconditions.** Phase 1 complete.

**Files to create.**
- `app/core/database.py` — engine, `SessionLocal`, `get_db` dependency
- `app/core/geo.py` — haversine distance + radius filtering
- `app/models/base.py` — declarative `Base`, timestamp mixin
- `app/models/{hub,vehicle,shipment,leg,recovery,auction,policy,audit,hub_candidate,model_artifact,user}.py`
- `app/models/enums.py` — status/strategy/role enumerations
- `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`
- `tests/test_database.py`, `tests/test_models.py`, `tests/test_geo.py`

**Files to modify.** `app/core/config.py` (add `database_url`, `db_echo`),
`app/main.py` (init DB on startup, add `database` readiness check),
`app/api/v1/routes/health.py` (report DB status), `requirements.txt`.

**Files NOT to touch.** Anything under `frontend/`, `e1-model/`,
`backend/credentials/`.

**Implementation steps.**

- **2.1** Add `DATABASE_URL` / `DB_ECHO` to `Settings`; resolve relative SQLite
  paths against `backend/`. *Test:* settings load, default is SQLite.
- **2.2** Create `database.py`: engine with `check_same_thread=False` for
  SQLite, `SessionLocal`, `get_db` generator, `init_db()`. Enable
  `PRAGMA foreign_keys=ON` via a connect event — SQLite ignores FKs otherwise.
  *Test:* connection opens; FK pragma is on.
- **2.3** Declarative `Base` + `TimestampMixin` (`created_at`, `updated_at`).
- **2.4** Enums: `ShipmentStatus`, `VehicleType`, `LegStatus`, `PlanStrategy`,
  `PlanStatus`, `AuctionStatus`, `PolicyModeName`, `CandidateStatus`, `UserRole`.
- **2.5** Geo entities: `Hub` (lat/lng), `Vehicle`. *Test:* CRUD + relationships.
- **2.6** `Shipment` with `temperature`, `lam`, `p_misplace`, `deadline_at`,
  `sla_penalty_per_hour`. *Test:* CRUD, FK enforcement.
- **2.7** `Leg` with capacity/residual (kg and m³) and schedule. *Test:* CRUD.
- **2.8** `RecoveryPlan` + `RecoveryPath` (ordered legs, `seq`). *Test:*
  ordered retrieval, cascade delete.
- **2.9** `Auction` + `Bid`. *Test:* CRUD, winner flag.
- **2.10** Product-layer tables: `User`, `AuditLog`, `PolicyMode` (singleton),
  `HubCandidate`, `ModelArtifact` (one active per name). *Test:* CRUD.
- **2.11** `geo.py`: `haversine_km`, `hubs_within_radius`. *Test:* known
  distances within tolerance; radius filter selects the right hubs.
- **2.12** Alembic init + initial migration. *Test:* `alembic upgrade head`
  creates every table; `downgrade base` drops them.
- **2.13** Wire DB into lifespan + `/ready`. *Test:* `/ready` reports
  `{"database": "ok"}`.

**Expected output.** `backend/sh205.db` containing 13 tables; `/ready` green.

**Dependencies.** SQLAlchemy 2.0, Alembic.

**Risks.** SQLite FK enforcement off by default (mitigated in 2.2); enum storage
portability (store as strings, not native enums); naive-vs-aware datetimes
(store UTC-naive consistently).

**Testing.** `pytest tests/test_database.py tests/test_models.py tests/test_geo.py`

**Validation.** Database file created; all tables present; CRUD round-trips;
haversine within 1% of reference; `alembic upgrade head` idempotent.

**Acceptance criteria.** Database starts; tables exist; CRUD test passes;
geo queries return correct results; full suite green.

**Rollback.** Delete `backend/sh205.db` and re-run `alembic upgrade head`. No
other phase depends on Phase 2 data content, only its shape.

---

## PHASE 3 — E1 integration ⛔ CRITICAL CHECKPOINT

**Objective.** Load the already-trained E1 artifacts and serve calibrated
`P(misplace)` through a model registry, without retraining or modifying them.

**Preconditions.** Phase 2 complete. Artifacts present at
`e1-model/softHack/artifacts/misplacement_classifier/v1/`.

**Files to create.** `app/engines/e1_misplacement/registry.py` (ModelRegistry),
`app/engines/e1_misplacement/features.py` (feature contract),
`app/engines/e1_misplacement/service.py`, `app/schemas/model.py`,
`app/api/v1/routes/model.py` (`GET /model/status`, `POST /model/reload`),
`tests/test_e1_*.py`.

**Files NOT to touch.** `e1-model/**` — **read-only**. Artifacts are never
rewritten, never re-pickled, never retrained.

**Implementation steps.**
- **3.1** Read `feature_schema.json` + `training_metadata.json`; derive the
  exact expected feature list and dtypes.
- **3.2** Verify the installed sklearn/numpy/scipy versions can unpickle
  `model.pkl`. **This is the phase's main risk** (constraint C7).
- **3.3** `ModelRegistry`: load model + pipeline at startup, expose
  `predict(features) -> float`, `status()`, `reload()`.
- **3.4** Seed a `ModelArtifact` row for v1 and mark it active.
- **3.5** Endpoints `/model/status` and `/model/reload`.
- **3.6** Wire registry into app lifespan and `/ready`.

**Testing.** Artifacts load; a known shipment yields a probability; probability
strictly within [0, 1]; unknown categories do not crash; missing feature raises
a clear error; `/model/status` reports `model_loaded: true`.

**Acceptance criteria.** E1 loads; test shipment produces `P(misplace)`;
probability in [0, 1]; preprocessing matches the artifact.

**Rollback.** Registry failure must degrade to `model_loaded: false` and a
`degraded` readiness state — it must never prevent the backend from starting.

---

## PHASE 4 — Simulator

Simulation clock, 30 hubs / 200 vehicles / 5 000 shipments, fixed seed,
tick loop, movement, capacity consumption, disruption injection.
`app/workers/simulator.py`, `app/workers/clock.py`, `app/services/world.py`.
**Validation:** world builds; `tick()` changes state; a fixed seed reproduces an
identical world; disruption flips a shipment to `MISPLACED`.

## PHASE 5 — E4 Adaptive Recovery Temperature

`T(s) = clamp(0,100, T_base + T_time + T_delay + T_cascade)`,
`λ(s) = sla_penalty_per_hour × (1 + T(s)/50)`. Policy modes re-weight `T_base`.
**Validation:** temperature rises as the deadline nears; λ tracks T; switching
policy mode changes output; result clamps to [0,100].

## PHASE 6 — Recovery Pressure Score

Normalised factors, weighted formula, threshold, Emergency Recovery Mode.
**Validation:** pressure rises with elapsed time and cascade depth; crossing the
threshold sets emergency mode; score stays in [0,1].

## PHASE 7 — E6 Piggy Router ⛔ CRITICAL CHECKPOINT

Time-expanded graph, label-setting RCSPP with dominance pruning, candidate
generation under capacity/deadline/transfer constraints, PIGGYBACK / DEDICATED /
HYBRID strategies, `w(e) = C_transit(e) + λ(s)·transit_hours(e) + handling_penalty(e)`,
k-best plans.
**Validation:** feasible route found; infeasible rejected; capacity respected;
deadline respected; k-best ordered by score.

## PHASE 8 — E7 Graph Memory

State representation, path + failed-path storage, dominance, backtracking,
warm-start. In-process cache behind a swappable interface (constraint C4).
**Validation:** failed path remembered; repeated bad path avoided; warm-start
measurably faster than cold.

## PHASE 9 — E5 Bounty Market

Eligible-vehicle gating, reverse auction, bids, Vickrey payment.
`MaxBounty = min(λ(s)·Δt_saved, C_dedicated − C_overhead)`,
`Payment = min(second_lowest_bid, MaxBounty)`.
**Validation:** auction opens; bids arrive; winner is lowest bidder; payment is
second-lowest capped at MaxBounty; no-bid auction closes cleanly.

## PHASE 10 — E2 Foresight Reservation

Critical fractile: buy ⟺ `P(misplace) ≥ Premium / (Premium + C_dedicated − E[Bounty])`.
**Validation:** reservation taken above threshold, rejected below; exercising a
held option is near-instant.

## PHASE 11 — E3 Hub Emergence

`HubScore(L) = usage_count(L,30d) × mean_risk(cell(L))`, candidate generation,
savings estimate, admin approval.
**Validation:** high-use/high-risk area produces a candidate; low-risk does not
dominate; approval writes a `Hub` row and an `AuditLog` entry.

## PHASE 12 — Route Fusion

Compatibility, combined capacity, deadline check, movement reduction, cost
comparison, utilisation.
**Validation:** compatible routes merge; incompatible stay separate; merged cost
≤ sum of separate costs.

## PHASE 13 — Recovery Cascade ⛔ CRITICAL CHECKPOINT

Dependency graph, impacted shipments/hubs/vehicles, priority + temperature +
pressure updates, re-planning, fixpoint iteration with a cycle guard.
**Validation:** one disruption propagates downstream; unaffected shipments
unchanged; cascade terminates (no infinite loop) under a bounded iteration cap.

## PHASE 14 — E8 Explainer

Selected-plan explanation, rejected alternatives with concrete reasons, and
route/cost/ETA/capacity evidence.
**Validation:** explanation is deterministic for identical input; every rejected
candidate carries a real reason, never a placeholder.

## PHASE 15 — E9 Outcome Learning

Predicted vs actual, error capture, recovery outcome log, training records.
**Validation:** each completed recovery writes one outcome row with correct
prediction error. Must not alter E1–E8 behaviour.

## PHASE 16 — Recovery Orchestrator ⛔ CRITICAL CHECKPOINT

Pipeline: E1 → Pressure → E4 → Cascade → E2 → E5 → E6 → E7 → Route Fusion →
final plan → E8.
**Validation:** one recovery request executes the full pipeline and produces a
committed plan plus an explanation.

## PHASE 17 — REST API

Full endpoint map from `SH.docx` §9: shipments, legs, vehicles, hubs,
hub-emergence, heatmap, reservations, auctions, policy-mode, simulation control,
model registry.
**Validation:** endpoint, validation, authorization and error-handling tests.

## PHASE 18 — WebSocket / realtime

`/ws/live`: shipment + vehicle updates, temperature, pressure, plan changes,
auction changes, cascade events, simulation ticks.
**Validation:** a backend event reaches a connected client; reconnection works.

## PHASE 19 — Firebase integration ⛔ CRITICAL CHECKPOINT

Firebase Admin token verification, role custom claims, `require_role`
dependency, Firestore notification writes. Credentials read from the existing
service-account file by path only (constraint C5).
**Validation:** valid token accepted; invalid rejected; role gate enforced;
notification document written.

## PHASE 20 — Google Maps integration

Route geometry, polylines, `/legs/{id}` click-info payload, markers, heatmap
feed, directions. Reuses the existing `gmaps.js` / `livemap.js` with its Leaflet
fallback.
**Validation:** map renders; route click returns leg detail; fallback works when
the Maps API is unavailable.

## PHASE 21 — Frontend integration ⛔ CRITICAL CHECKPOINT

Replace mock data in `frontend/sidecar-site/js/data.js` with real API calls,
incrementally. **Do not rebuild the UI** (constraint C6).
**Validation:** every screen loads; real backend data appears; interactions call
the backend; the site still works with the backend down (graceful degradation).

## PHASE 22 — Metrics

SLA%, recovery cost, % recovered via existing capacity, vehicle-km avoided,
re-plan latency, premium burn ratio, recovery time, piggyback/dedicated/hybrid
rates.
**Validation:** metrics change after a simulation run and match hand-computed
values on a small fixture.

## PHASE 23 — End-to-end demo ⛔ CRITICAL CHECKPOINT

The `SH.docx` §15 script: inject disruption → E1 → Pressure → Temperature →
Cascade → Piggy Routing → Graph Memory → Bounty → Route Fusion → final plan →
Explainer → driver update → frontend update.
**Validation:** the complete flow succeeds repeatedly from a clean seed.

## PHASE 24 — Hardening

Error handling, logging, configuration, security, cleanup, performance, coverage.
**Validation:** suite green; no secrets in logs, responses or git; clean startup.

## PHASE 25 — Final documentation

README, architecture, API reference, demo script, local deployment,
troubleshooting.

---

## 3. Dependency graph

```
Phase 1 (foundation)
   └─> Phase 2 (database)
          ├─> Phase 3  (E1) ────────────────┐
          └─> Phase 4  (simulator)          │
                 ├─> Phase 5  (E4 Temp) <───┤
                 │      └─> Phase 6 (Pressure)
                 │             └─> Phase 7 (E6 Router)
                 │                    ├─> Phase 8  (E7 Graph Memory)
                 │                    └─> Phase 12 (Route Fusion)
                 ├─> Phase 9  (E5 Bounty)   [needs E4 λ]
                 ├─> Phase 10 (E2 Foresight)[needs E1 + E5]
                 └─> Phase 11 (E3 Hub Emergence) [needs E1 risk + usage]

Phase 13 (Cascade) <- needs 5, 6, 7
Phase 14 (E8 Explainer) <- needs 7, 9, 12  (consumes many engines' output)
Phase 15 (E9 Learning)  <- needs 3, 16
Phase 16 (Orchestrator) <- needs 3,5,6,7,8,9,10,12,13,14
Phase 17 (REST) <- 16 ;  Phase 18 (WS) <- 17 ;  Phase 19 (Firebase) <- 17
Phase 20 (Maps) <- 17 ;  Phase 21 (Frontend) <- 17,18,19,20
Phase 22 (Metrics) <- 21 ;  Phase 23 (Demo) <- 22 ;  24 <- 23 ;  25 <- 24
```

Engine-level flow (runtime, per recovery):

```
E1 ─> Pressure ─> E4(λ) ─> Cascade ─> E2 ─> E5 ─> E6 ─> E7 ─> Route Fusion ─> Plan ─> E8
                                                                                 └─> E9
```

---

## 4. File change map

**Create** — everything under `backend/app/`, `backend/alembic/`,
`backend/tests/`, `docs/`.

**Modify** — `backend/requirements.txt`, `backend/.env.example`,
`backend/README.md`, `backend/app/main.py` (router + lifespan wiring only),
and in Phase 21 only: `frontend/sidecar-site/js/data.js`,
`frontend/sidecar-site/js/config.js` (add `API_BASE_URL`).

**Preserve unchanged** — all `frontend/sidecar-site/*.html`, `css/styles.css`,
`js/*.js` except the two above, `vendor/leaflet.*`.

**Never modify** — `e1-model/**` (artifacts and training code),
`backend/credentials/**`, `frontend/.env`, `SH.docx`, `Implementation.md`.

| Frontend file | Disposition |
|---|---|
| `js/data.js` | **Integrated** — mock functions become API calls, signatures kept |
| `js/config.js` | **Lightly modified** — add `API_BASE_URL` |
| `js/gmaps.js`, `js/livemap.js`, `js/map.js` | **Reused unchanged** — feed real geometry |
| `js/page-*.js` | **Reused unchanged** — they consume `data.js` |
| `*.html`, `css/styles.css` | **Reused unchanged** |

---

## 5. Risk register

| Risk | Impact | Detection | Prevention | Recovery |
|---|---|---|---|---|
| E1 unpickle fails on Python 3.14 / sklearn mismatch | **High** — Phase 3 blocked | Phase 3.2 version check | Verify before building the registry | Pin the training-time sklearn; if no cp314 wheel exists, escalate — may need a second interpreter |
| SQLite FK constraints silently ignored | Medium — orphan rows | Phase 2 FK test | `PRAGMA foreign_keys=ON` on every connect | Re-run migration |
| SQLite write contention under the tick loop | Medium | Simulator load test in Phase 4 | Single writer; short transactions | WAL mode; ultimately native PostgreSQL |
| Frontend API mismatch | High — Phase 21 rework | Contract tests in Phase 17 | Derive schemas from what `data.js` already returns | Adapter layer in `data.js` |
| Mock state assumptions baked into UI | Medium | Phase 21 screen-by-screen check | Keep `data.js` function signatures identical | Revert `data.js`, reconnect one screen at a time |
| Google Maps key restricted/absent | Low — Leaflet fallback exists | Map fails to load | Existing fallback path | Leaflet |
| Firebase token verification misconfigured | High — Phase 19 blocked | Phase 19 auth tests | Path-only credential reference | Dev bypass flag, disabled by default |
| Cascade infinite loop | High — hangs the demo | Phase 13 termination test | Bounded iteration cap + visited set | Abort and keep the last good plan |
| Secrets leaked into logs or git | High | Phase 24 scan | `.gitignore`, never log config values | Rotate the key |
| Plan drift from `SH.docx` | Medium | Formula tests use the §16 sheet verbatim | Cite formulas in code comments | Re-derive from §16 |

---

## 6. Local run procedure (no Docker)

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --reload

# Frontend (static site — no build step, no package.json)
cd frontend/sidecar-site
python -m http.server 5500
```

Backend: <http://localhost:8000> · Docs: <http://localhost:8000/docs> ·
Frontend: <http://localhost:5500>
