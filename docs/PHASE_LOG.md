# SH-205 — Phase Execution Log

Append-only. Each entry records one completed phase or approved change.
Never overwrite previous entries.

---

## PHASE 1 — Backend Foundation

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
A FastAPI backend skeleton: application factory, environment-driven
configuration, unified logging, health/readiness endpoints, CORS for the
frontend origins, and the full package structure for engines E1–E9.

### Files created
| File | Purpose |
|---|---|
| `backend/app/main.py` | App factory, CORS middleware, lifespan hooks, router wiring |
| `backend/app/core/config.py` | Typed `Settings` from env + `.env` |
| `backend/app/core/logging.py` | Text/JSON formatter, unified root + uvicorn handlers |
| `backend/app/api/v1/router.py` | Aggregates all v1 routers |
| `backend/app/api/v1/routes/health.py` | `GET /health`, `GET /ready` |
| `backend/app/schemas/health.py` | `HealthResponse`, `ReadinessResponse` |
| `backend/app/engines/e1_misplacement/` … `e9_learning/` | Engine package placeholders |
| `backend/app/{models,services,workers,schemas}/` | Layer placeholders |
| `backend/requirements.txt`, `.env.example`, `pytest.ini`, `README.md` | Project config |
| `backend/tests/test_health.py`, `test_config.py` | 16 tests |
| `.gitignore` (root) | Protects `backend/credentials/`, `.env` |

### Important logic
- **Config**: `CORS_ORIGINS` accepts a comma-separated string via a
  `field_validator`, because pydantic-settings would otherwise JSON-decode a
  list field and make `.env` awkward to hand-write. Settings are `lru_cache`d.
- **Logging**: uvicorn's own handlers are cleared and set to `propagate=True`,
  so application and server logs share one format instead of printing twice.
- **Routing**: health is mounted both at root (`/health`, for probes) and under
  `/api/v1`, so `main.py` never needs editing when new routers are added.
- **Readiness**: `/ready` returns an empty `checks` map in Phase 1; later phases
  add database and model entries.

### Automatic tests performed
`pytest` — 16 tests: root banner, `/health` shape, versioned-prefix health,
`/ready`, OpenAPI schema, CORS simple request, CORS preflight, 404 handling,
settings caching, CORS-origin parsing (string + list), log-level normalisation,
`is_production`, path resolution, JSON formatter, handler installation.

Plus live HTTP validation against a real uvicorn process on port 8123:
`/health` 200, `/api/v1/health` 200, `/ready` 200, `/docs` 200,
CORS preflight 200 with correct `access-control-allow-origin`.

### Automatic test results
**16 passed / 16** in 0.87 s. Live server started and shut down cleanly.

### Errors encountered
`pip install` failed building **`pydantic-core`** from Rust source.
Root cause: this machine runs **Python 3.14**, and pydantic 2.11.9 publishes no
cp314 wheel, so pip fell back to a `maturin`/cargo build that failed for lack of
a working MSVC link toolchain.

### Fixes applied
Pinned **pydantic ≥ 2.12** (2.12.5 / pydantic-core 2.41.5 ship cp314 wheels) and
bumped FastAPI to 0.128.0 and uvicorn to 0.38.0 to match. Recorded the
constraint in `requirements.txt` and `backend/README.md`.

### Final status
✅ All acceptance criteria met: backend starts, health endpoint responds,
no frontend changes required.

### Remaining limitations / dependencies
- Python 3.14 constrains future ML dependencies — **flagged as the main Phase 3
  risk** (sklearn/numpy/scipy cp314 wheel availability for unpickling `model.pkl`).
- `/ready` has no real dependency checks until Phase 2.
- Observed but not acted on (out of scope): a live Google Maps API key is
  committed in plaintext at `frontend/sidecar-site/js/config.js:6`.

---

## CHANGE RECORD — Infrastructure constraint: no Docker

**Date:** 2026-09-19 · **Status:** ✅ APPLIED · **Type:** Requirement change
(user-directed, mid-Phase 2)

### Requirement
Docker is not available on this machine and is not wanted. The project must not
install, require, or depend on Docker or docker-compose anywhere. Everything
must run directly on the local machine. PostgreSQL/Redis to be used only if
genuinely required; otherwise a simpler local alternative. Firebase stays
externally connected via the existing configuration.

### Decisions taken
| Component | `SH.docx` specifies | Now using | Rationale |
|---|---|---|---|
| Database | PostgreSQL + PostGIS | **SQLite** via SQLAlchemy | Ships with Python; no server/service/container. `DATABASE_URL` still swaps to native PostgreSQL with zero code change. |
| Geo queries | PostGIS `ST_DWithin` | **Haversine helper** | At 30 hubs / 200 vehicles / 5 000 shipments the difference is immaterial. |
| Cache | Redis | **In-process cache** behind a `get/set/delete` interface | Single-process prototype; Redis can be dropped in later untouched. |
| Deployment | Cloud Run container | **Local `uvicorn`** | No container runtime available or wanted. |

Firebase is unaffected and remains externally connected.

### Files created/modified
| File | Change |
|---|---|
| `docs/IMPLEMENTATION_PLAN.md` | **Created.** Did not previously exist. Records constraints C1–C7, all 25 phases, dependency graph, file change map, risk register, local run procedure. |
| `backend/Dockerfile` | **Removed** (constraint C1) |
| `backend/.dockerignore` | **Removed** (constraint C1) |
| `backend/requirements.txt` | Removed `GeoAlchemy2` and `psycopg`; added `SQLAlchemy==2.0.44`, `alembic==1.20.0` |
| `backend/.env.example` | `DATABASE_URL=sqlite:///./sh205.db` as the default; removed `REDIS_URL`; kept a commented PostgreSQL line |
| `backend/README.md` | Docker section replaced with local-only instructions |
| `srihitha.md` | **Created** (this file) |

### Errors encountered
1. `alembic==1.16.6` does not exist on PyPI — the install aborted.
   **Fix:** re-pinned to `alembic==1.20.0`.
2. Docker Desktop had been launched while probing for a PostgreSQL option.
   **Fix:** stopped the process; no containers were ever created or pulled.

### Verification after the change
- No Docker files remain in the project (`backend/Dockerfile`,
  `.dockerignore` deleted; only `Implementation.md`, the user's own source
  document, still mentions Docker and was deliberately left untouched).
- No Phase 2 packages had been installed when the change arrived, so the
  dependency set is clean.
- Phase 1 re-verified after removal: see the Phase 1 re-validation note below.

### Final status
✅ Applied. Phase 1 remains intact and passing. Phase 2 restarts from a clean
state on SQLite.

### Remaining limitations / dependencies
- SQLite serialises writers — acceptable for a single-process demo, not for
  production. Revisit only if the Phase 4 tick loop shows write contention.
- `SH.docx` §1/§13 still describe PostgreSQL/PostGIS/Redis/Cloud Run. The
  architecture shape is unchanged; only the local backing stores differ. This
  divergence is recorded in `docs/IMPLEMENTATION_PLAN.md` §0.

---

## PHASE 2 — Database Foundation

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
The full relational schema for SH-205 on **SQLite** (per constraint C3), with
SQLAlchemy 2.0 declarative models, Alembic migrations, a session lifecycle, and
a haversine geo helper standing in for PostGIS `ST_DWithin`.

**13 tables:** `hubs`, `vehicles`, `legs`, `shipments`, `recovery_plans`,
`recovery_paths`, `auctions`, `bids`, `users`, `audit_logs`, `policy_modes`,
`hub_candidates`, `model_artifacts`.

### Files created
| File | Purpose |
|---|---|
| `backend/app/core/database.py` | Engine, `SessionLocal`, `get_db`, `init_db`, `check_database` |
| `backend/app/core/geo.py` | `haversine_km`, `bounding_box`, `within_radius`, `path_length_km` |
| `backend/app/models/base.py` | `Base`, `TimestampMixin`, `utcnow`, constraint naming convention |
| `backend/app/models/enums.py` | 11 string enumerations |
| `backend/app/models/network.py` | `Hub`, `Vehicle`, `Leg` |
| `backend/app/models/shipment.py` | `Shipment` + temperature banding |
| `backend/app/models/recovery.py` | `RecoveryPlan`, `RecoveryPath`, `Auction`, `Bid` |
| `backend/app/models/product.py` | `User`, `AuditLog`, `PolicyMode`, `HubCandidate`, `ModelArtifact` |
| `backend/alembic.ini`, `alembic/env.py`, `alembic/script.py.mako` | Migration tooling |
| `backend/alembic/versions/fe6b97d045c8_initial_schema.py` | Initial migration |
| `backend/tests/conftest.py` | Throwaway-DB fixtures (`db`, `hubs`, `vehicle`, `shipment`) |
| `backend/tests/test_database.py`, `test_models.py`, `test_geo.py` | 52 new tests |

### Files modified
| File | Change |
|---|---|
| `backend/app/core/config.py` | Added `database_url`, `db_echo`, `is_sqlite`, `resolved_database_url` |
| `backend/app/main.py` | `init_db()` in lifespan |
| `backend/app/api/v1/routes/health.py` | `/ready` now reports `{"database": "ok"}`; switched to `def` so the blocking check uses the threadpool |
| `backend/tests/test_health.py` | Readiness test updated for the new contract |

### Important logic
- **SQLite FK enforcement.** SQLite ignores `FOREIGN KEY` unless enabled per
  connection. A `connect` event issues `PRAGMA foreign_keys=ON` (and
  `journal_mode=WAL`), and `test_leg_foreign_key_is_enforced` proves it — without
  this, orphan rows would pass silently.
- **Path anchoring.** `resolved_database_url` anchors relative SQLite paths to
  `backend/`, so the DB file does not follow the current working directory.
- **Portability.** Enums stored as `String`, not native DB enums; `weights_json`
  and `metrics_json` stored as `Text`. The schema is dialect-neutral, so
  `DATABASE_URL` alone moves it to PostgreSQL.
- **UTC-naive datetimes** everywhere (`utcnow()`), because SQLite has no
  timezone-aware type and mixing the two produces silently wrong comparisons.
- **Engine fields live on the entities** they describe: `p_misplace` (E1),
  `temperature`/`lam` (E4), `pressure` (Phase 6), `cascade_depth` (Phase 13), so
  the dispatcher queue sorts without recomputation.
- **`rejection_reason`** on `RecoveryPlan` is populated by E6 and consumed
  verbatim by E8, so the Explainer never shows a placeholder.
- **Constraint naming convention** on `MetaData` so Alembic can autogenerate
  stable migrations (SQLite otherwise emits unnamed constraints).

### Automatic tests performed
- `test_geo.py` (12): reference distances Delhi–Mumbai (~1153 km) and
  Delhi–Bengaluru (~1740 km) within 1%, symmetry, 1° latitude ≈ 111 km,
  bounding-box containment, longitude widening near the pole, pole clamping,
  radius selection + ordering, polyline length.
- `test_models.py` (28): CRUD for all 13 tables, unique constraints (hub code,
  user email, artifact name+version, one bid per vehicle per auction, unique
  path seq per plan), FK enforcement, cascade deletes
  (vehicle→legs, plan→paths, shipment→plans→paths, auction→bids),
  leg transit hours, capacity checks, temperature banding (6 parametrised cases),
  deadline arithmetic.
- `test_database.py` (11): SQLite default, path anchoring, `:memory:`
  passthrough, PostgreSQL URL passthrough, FK pragma, metadata completeness,
  session lifecycle, health check, and **real `alembic upgrade head` /
  `downgrade base` subprocess runs** against throwaway database files.
- `test_health.py`, `test_config.py` (16, from Phase 1) re-run.

### Automatic test results
**68 passed / 68** in 6.75 s.

Live verification: `alembic upgrade head` created 14 tables (13 + `alembic_version`);
server startup logged `Database ready (sqlite, 13 tables)`;
`GET /ready` → `{"status":"ready","checks":{"database":"ok"}}`.

### Errors encountered
1. **`alembic==1.16.6` does not exist on PyPI** — install aborted.
   *Fix:* re-pinned to `alembic==1.20.0`.
2. **`test_ready_returns_ready` failed** — the Phase 1 test asserted
   `checks == {}`, but Phase 2 deliberately adds a database entry.
   *Fix:* updated the assertion to `checks["database"] == "ok"`. This is a
   contract change, not a regression.

### Fixes applied
Both fixed and re-verified; suite green at 68/68.

### Final status
✅ All Phase 2 acceptance criteria met:
- database starts ✅
- tables exist ✅ (13)
- CRUD test passes ✅
- geo queries work where required ✅

### Remaining limitations / dependencies
- **No PostGIS.** Geo-pruning uses haversine. Adequate at prototype scale;
  revisit only if E6 (Phase 7) shows a performance problem.
- **SQLite serialises writers.** Watch for contention when the Phase 4 tick
  loop starts writing every tick.
- **`Reservation` table deferred to Phase 10** (E2 Foresight). It is not in the
  Phase 2 table list and nothing before Phase 10 reads it.
- `PolicyMode` and `ModelArtifact` singleton/active-row invariants are enforced
  in application code, not by a DB constraint — SQLite has no partial unique
  indexes. To be enforced in Phases 3 and 17.

---

## PHASE 3 — E1 Integration ⛔ CRITICAL CHECKPOINT

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE — awaiting manual verification

### What was implemented
A `ModelRegistry` that loads the already-trained E1 misplacement classifier
from `e1-model/` and serves calibrated `P(misplace)` through REST endpoints,
per SH.docx §10.3. **E1 was not retrained and no artifact was modified.**

### Files created
| File | Purpose |
|---|---|
| `backend/app/engines/e1_misplacement/features.py` | Frozen 8-feature contract, validation, probability clamping |
| `backend/app/engines/e1_misplacement/registry.py` | `ModelRegistry`: background load, predict, batch predict, reload, status |
| `backend/app/engines/e1_misplacement/service.py` | `E1Service` + domain to feature mapping (assumptions documented in-module) |
| `backend/app/schemas/model.py` | Status / prediction request+response schemas |
| `backend/app/api/v1/routes/model.py` | `/model/status`, `/model/reload`, `/model/predict`, `/model/predict/batch` |
| `backend/app/services/model_artifacts.py` | Registers the bundled artifact, enforces one active row per name |
| `backend/tests/test_e1_features.py` | 16 contract tests (no model load) |
| `backend/tests/test_e1_registry.py` | 17 registry tests against the real artifacts |
| `backend/tests/test_e1_api.py` | 13 endpoint tests |

### Files modified
| File | Change |
|---|---|
| `backend/app/core/config.py` | `e1_artifact_dir`, `e1_model_version`, `e1_eager_load`, `e1_load_timeout_seconds`, `e1_artifact_path` |
| `backend/app/main.py` | Registers the artifact row and starts the background model load in lifespan |
| `backend/app/api/v1/router.py` | Mounted the model router |
| `backend/app/api/v1/routes/health.py` | `/ready` now reports `e1_model` state |
| `backend/pytest.ini` | Added the `slow` marker |
| `backend/requirements.txt` | `scikit-learn==1.9.0`, `pandas`, `joblib` (+ numpy/scipy transitively) |

### Files NOT touched
`e1-model/**` — read-only throughout. No artifact was re-pickled or retrained.

### Important logic
- **Background loading.** `model.pkl` is **205 MB** and takes **~25 s to
  unpickle cold** (~2.4 s warm, from OS page cache). Loading it inline would
  block startup for 25 s every run. It loads on a daemon thread instead, so the
  API serves immediately and `/model/status` reports
  `unloaded -> loading -> loaded/failed`. A prediction issued mid-load waits on
  the load event rather than failing.
- **E1 is deliberately NOT a readiness gate.** `/ready` reports the model state
  but stays `ready` as long as the database is up, so a model failure degrades
  the service instead of taking the backend down.
- **Feature-order verification at load time.** `_verify_schema` compares the
  artifact's `feature_ordering` against the code's `FEATURE_ORDER` and refuses
  to load on mismatch. Drift here would otherwise yield confidently wrong
  probabilities rather than an error. A test asserts the same invariant.
- **Probability clamping** into [0,1] with an explicit NaN check, because E2's
  critical-fractile maths divides by terms derived from this value.
- **One active artifact per name** enforced in `sync_local_artifact` — SQLite
  has no partial unique index.
- **`artifact_dir` is stripped from `/model/status`** so the API does not leak
  the server's filesystem layout.

### Automatic tests performed
- **Contract (16):** feature order matches `feature_schema.json` exactly;
  categorical/numeric split matches; missing / unexpected / None / wrong-type
  fields rejected; bool coercion; clamping incl. NaN; route-code composition;
  vehicle-type to carrier mapping; hour extraction.
- **Registry (17):** artifacts exist; loads as `RandomForestClassifier` v1;
  provenance (sklearn 1.9.0, trained_at, metrics); missing artifacts raise
  clearly; **background load failure is recorded, not raised**; predict-before-load
  raises `ModelNotReadyError`; probability bounded and non-NaN; determinism;
  batch equals single; empty batch; 24-row bounds sweep; **features actually move
  the output** (guards a degenerate pipeline); unknown categories do not crash;
  reload preserves predictions; service facade single + batch.
- **API (13):** `/model/status` loaded/version/class; feature contract exposed;
  no filesystem leak; versioned prefix; `/model/predict` bounded probability;
  422s for missing field, hour 25, weather_flag 7; batch returns one probability
  per row; empty batch rejected; `/model/reload` 200; `/ready` reports model
  state; `ModelArtifact` row registered and active.

### Automatic test results
**118 passed / 118** in 11.24 s (30 model-loading tests + 88 fast).

Live server verification:
- `/ready` answered `{"database":"ok","e1_model":"loading"}` **while the model
  was still loading** — confirming non-blocking startup.
- `/model/status` returned `loaded`, v1, RandomForestClassifier, sklearn 1.9.0, 2.36 s.
- `POST /model/predict` returned `{"p_misplace":0.6,"model_version":"v1"}`.
- `/ready` returned `{"database":"ok","e1_model":"loaded"}`.

### Errors encountered
1. **Feared Python 3.14 unpickling failure did not occur.** The metadata shows
   E1 was trained on **Python 3.14.3 + sklearn 1.9.0** — the same interpreter
   family as this machine. Installing `scikit-learn==1.9.0` loaded the artifact
   with **zero version warnings**. The Phase 1 risk is closed.
2. **First probe returned exactly 0.500.** Root cause: the probe row used
   invented categories (`hub="H00"`, `carrier="C0"`). Real vocabulary is
   `route=R000..R499`, `hub=F000..F199`, `carrier=air|multi|sea|rail`. With real
   values, probabilities spread 0.04 to 0.98 (std 0.319, 62 distinct values).
   Not a defect — but it is exactly how the simulator will behave (see below).

### Fixes applied
Both resolved; suite green at 118/118.

### Final status
✅ All Phase 3 acceptance criteria met:
- E1 loads ✅
- test shipment produces `P(misplace)` ✅
- probability within 0–1 ✅ (asserted on every path, incl. a 24-row sweep)
- model preprocessing matches artifact ✅ (feature ordering verified at load)

### ⚠️ Remaining limitations / dependencies — READ BEFORE THE DEMO

1. **E1 has no real predictive power on its own test set.**
   From the artifact's own `metrics.json`:

   | Metric | Test value | Meaning |
   |---|---|---|
   | ROC-AUC | **0.4999** | Exactly random (0.5 = coin flip) |
   | PR-AUC | 0.3153 | vs 0.3056 base rate — about +1% over guessing |
   | Accuracy | 0.5945 | Below the 0.694 from always predicting "not misplaced" |
   | Brier | 0.2430 | Poorly calibrated |

   This is a **property of the trained model, not of this integration.** The
   integration is correct and fully tested. Flagging it because SH.docx §10.2
   step 5 stresses that E2's critical-fractile maths needs *well-calibrated*
   probabilities, and these are not. **E1 was not retrained — that was explicitly
   out of scope.** Options, for the owner's decision: (a) demo as-is and describe
   E1 as a risk-signal placeholder, (b) retrain E1 as a separate task, (c) proceed
   and revisit before Phase 10 (E2), which is where calibration actually bites.

2. **Simulator vocabulary will not match training vocabulary.** E1 learned
   `route=R000..R499`, `hub=F000..F199`. The SH-205 simulator will emit codes
   like `DEL-BOM` / `DEL`. The fitted OneHotEncoder handles unknown categories
   without crashing (tested), but those rows are then driven only by the four
   numeric features. Documented in `service.py`'s module docstring.

3. **`sorting_method` is a constant** (`"unknown"`) — one value in the whole
   training set, so it contributes nothing.

4. **Cold start about 25 s.** First load after a reboot reads 205 MB from disk.
   Mitigated by background loading, but for the jury demo, **start the backend
   a minute before presenting** and confirm `/model/status` shows `loaded`.

5. **`/model/reload` is currently unauthenticated.** SH.docx §12 requires
   admin-only. The role guard arrives in Phase 19.

---

### MANUAL JURY TEST CASES — PHASE 3

Start the backend first:

    cd C:\projects\CSH\backend
    .venv\Scripts\python.exe -m uvicorn app.main:app --reload

Wait until the log shows `E1 loaded: misplacement_classifier v1`.

---

**TEST 3.1 — Backend starts without waiting for the 205 MB model**

*Steps:* Start the backend. **Within 2 seconds**, in another terminal run:
`curl http://localhost:8000/ready`

*Expected:* An immediate `200` with
`{"status":"ready","checks":{"database":"ok","e1_model":"loading"}}`
(or `"loaded"` if the file was already cached).

*Failure indication:* The command hangs for about 25 s, or connection refused.
That means the model is blocking startup.

---

**TEST 3.2 — The model reports itself loaded, with real provenance**

*Steps:* `curl http://localhost:8000/model/status`

*Expected:* `model_loaded: true`, `state: "loaded"`,
`name: "misplacement_classifier"`, `version: "v1"`,
`model_class: "RandomForestClassifier"`, `sklearn_version: "1.9.0"`.

*Failure indication:* `state: "failed"` with an `error` field — the artifact
is missing or unreadable. `state` stuck on `"loading"` past about 60 s — the
load thread is wedged.

---

**TEST 3.3 — A shipment produces a probability between 0 and 1** (the core acceptance criterion)

*Steps:*

    curl -X POST http://localhost:8000/model/predict -H "Content-Type: application/json" -d "{\"route\":\"R000\",\"hub\":\"F000\",\"carrier\":\"air\",\"congestion_index\":0.42,\"num_handoffs\":3,\"weather_flag\":0,\"hour_of_day\":17}"

*Expected:* `{"p_misplace": <a number between 0.0 and 1.0>, "model_version":"v1"}`
— for this exact input, `0.6`.

*Failure indication:* `503` (model not ready — wait and retry), `422`
(malformed body), or a value outside 0–1 (clamping broken).

---

**TEST 3.4 — Different shipments get different risk scores**

*Steps:* Run TEST 3.3 three times, changing only `hub`: `F000`, `F050`, `F150`.

*Expected:* **At least two different `p_misplace` values.** This proves the
preprocessing pipeline is genuinely wired, not returning a constant.

*Failure indication:* All three identical — especially all exactly `0.5`. That
means the one-hot encoder is seeing unknown categories (check the codes are
from `R000-R499` / `F000-F199`) or the pipeline is not being applied.

---

**TEST 3.5 — Invalid input is rejected, not silently scored**

*Steps:* Send a request with `"hour_of_day": 25`.

*Expected:* `422 Unprocessable Entity`.

*Failure indication:* A `200` with a probability — validation is not running.

---

**TEST 3.6 — Hot-swap without restart (the MLOps pitch beat, SH.docx §10.4)**

*Steps:* With the backend running, `curl -X POST http://localhost:8000/model/reload`

*Expected:* `200` with `model_loaded: true`. The server log shows
`E1 loaded: misplacement_classifier v1` again. **No restart.**

*Failure indication:* `503` with a reason, or the process dies.

---

**TEST 3.7 — A missing model degrades the service instead of killing it**

*Steps:* Stop the backend. Set `E1_ARTIFACT_DIR=does/not/exist` in
`backend/.env`. Start the backend. Then run `curl http://localhost:8000/ready`
and `curl http://localhost:8000/model/status`.

*Expected:* The backend **still starts**. `/ready` returns `status: "ready"`,
`checks.e1_model: "failed"`. `/model/status` returns `model_loaded: false` with
an `error` naming the missing file.
**Remove the line from `.env` afterwards and restart.**

*Failure indication:* The backend crashes on startup, or `/ready` returns 503.

---

**Interactive alternative:** all of the above are clickable at
<http://localhost:8000/docs>.

### PHASE 3 MANUAL TEST EXECUTION — run by Claude on request, 2026-09-19

The owner delegated the manual jury tests rather than running them by hand.
All seven were executed against a live server on `127.0.0.1:8000` from a
clean database.

| # | Test | Result | Evidence |
|---|---|---|---|
| 3.1 | Non-blocking startup | ✅ PASS | First `/ready` at **1831 ms**: `{"database":"ok","e1_model":"loading"}` |
| 3.2 | Status + provenance | ✅ PASS | `loaded`, v1, RandomForestClassifier, sklearn 1.9.0, load 2.68 s |
| 3.3 | Probability in [0,1] | ✅ PASS | `{"p_misplace":0.6,"model_version":"v1"}` |
| 3.4 | Inputs move the output | ✅ PASS | F000 → 0.60, F050 → 0.61, F150 → 0.55 (3 distinct values) |
| 3.5 | Invalid input rejected | ✅ PASS | `422` — "Input should be less than or equal to 23" |
| 3.6 | Hot reload, no restart | ✅ PASS | `200`, `model_loaded: true`, reload 0.27 s, server alive after |
| 3.7 | Missing artifact degrades | ✅ PASS | Backend still started; `e1_model: "failed"`; error named the missing path |
| — | Bonus: predict while failed | ✅ PASS | `503` with a clear reason rather than a crash |

#### Error encountered during manual testing
**First run of TEST 3.1 produced a false PASS** (`e1_model: "loaded"` after
330 ms, which is impossible for a 205 MB artifact).

*Root cause:* a stale uvicorn process from an earlier step was still bound to
port 8000. The newly launched server logged
`[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000)`
and shut itself down, so the probe was answering from the **old** process.
The database file was also locked (`Device or resource busy`) by that process.

*Fix:* killed all Python processes, confirmed port 8000 free, deleted
`sh205.db*`, and re-ran from a genuinely clean start. TEST 3.1 then correctly
reported `e1_model: "loading"` at 1831 ms.

*Operational lesson for the demo:* **if a previous backend is still running, a
newly started one exits silently and you will be testing the old build.**
Before demoing, confirm with:
`Get-NetTCPConnection -LocalPort 8000 -State Listen`

#### Cleanup
`backend/.env` was never created, so the TEST 3.7 `E1_ARTIFACT_DIR` override
existed only as a one-shot environment variable and left nothing behind.

#### Phase 3 sign-off
✅ Verified by execution. Proceeding to Phase 4 (Simulator).

---

## PHASE 4 — Simulator

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
The simulated world and tick loop from SH.docx §14 block 0: a simulation
clock, deterministic world generation (30 hubs / 200 vehicles / 5 000
shipments / 600 legs from a fixed seed), movement, capacity accounting, and
three kinds of injectable disruption.

### Files created
| File | Purpose |
|---|---|
| `backend/app/models/simulation.py` | `ShipmentLeg` — which shipment rides which leg |
| `backend/app/workers/clock.py` | `SimulationClock` — thread-safe simulated time |
| `backend/app/workers/world.py` | Deterministic world builder, 30 real Indian hub locations |
| `backend/app/workers/simulator.py` | `Simulator`: tick, assignment, disruptions, state |
| `backend/app/schemas/simulation.py` | Request/response schemas |
| `backend/app/api/v1/routes/simulation.py` | `/simulate/state`, `/reset`, `/tick`, `/inject-disruption` |
| `backend/alembic/versions/9dc5be201c21_add_shipment_legs.py` | Migration for the new table |
| `backend/tests/test_simulator.py` | 31 tests |
| `backend/tests/test_simulation_api.py` | 12 tests |

### Files modified
| File | Change |
|---|---|
| `backend/app/models/shipment.py` | `legs` relationship |
| `backend/app/models/network.py` | `Leg.shipment_links` relationship |
| `backend/app/models/__init__.py` | Exported `ShipmentLeg` |
| `backend/app/api/v1/router.py` | Mounted the simulation router |

### Schema addition (documented deviation)
`shipment_legs` was **not** in the Phase 2 table list, but SH.docx §6.1
requires the leg info panel to list "shipments currently aboard", and the
simulator needs to record which shipment rides which movement. Added as
migration `9dc5be201c21`. 14 tables → **15**.

### Important logic
- **Determinism.** Everything derives from `random.Random(spec.seed)`. A test
  asserts two builds with seed 42 produce byte-identical shipments, and that
  seed 99 produces a different world. This is what makes the demo repeatable.
- **Real hub coordinates.** 30 actual Indian cities, so map rendering is
  plausible and distances are meaningful. Road distance is great-circle
  × 1.35 (typical Indian highway factor) at 45 km/h average.
- **Capacity is conserved.** Booking a shipment onto a leg subtracts from
  `residual_kg`/`residual_m3`; alighting or being misplaced adds it back,
  clamped at the leg's total capacity. Overloading raises `ValueError` at
  booking time rather than being discovered later — capacity is a hard E6
  constraint.
- **Initial itineraries.** The builder books each shipment onto a direct
  origin→destination leg where one exists with capacity and an arrival inside
  the deadline. Without this the world was static (ticks moved zero cargo).
  Shipments with no matching direct leg stay `PENDING` — realistically, those
  are the ones awaiting dispatch and the ones E6 will have to route.
- **`clear_world` preserves configuration.** Users, policy modes and model
  artifacts survive a rebuild; only simulation output is deleted.
- **Simulator holds no engine logic.** E1–E9 read the state it produces. This
  keeps the simulator testable with no engine present.

### Automatic tests performed
- **Clock (5):** starts at zero; advances by tick_minutes; snapshot elapsed
  hours; reset rewinds; rejects `tick_minutes=0` and `advance(0)`.
- **Distance (2):** road distance exceeds great-circle by the expected factor;
  travel time has a 0.5 h floor.
- **World generation (6):** requested counts; **same seed → identical world**;
  different seed → different world; rebuild replaces rather than appends;
  internal consistency (origin ≠ destination, arrival > departure,
  0 ≤ residual ≤ capacity); `clear_world` preserves configuration rows.
- **Tick (6):** advances the clock; departs due legs; **tick changes state**;
  shipment rides a leg from departure to delivery; vehicle position follows
  its leg; overdue shipments counted.
- **Capacity (3):** assignment consumes capacity; overload refused;
  capacity returns on alighting.
- **Disruptions (7):** misplacement changes shipment state; can target a
  specific shipment; misplacing releases capacity; vehicle delay pushes
  arrival times out and marks legs DELAYED; hub closure cancels its legs;
  **unaffected shipments stay untouched**; empty world fails clearly.
- **State (2):** counts by status; status changes tracked.
- **API (12):** reset builds requested world; state reports it; tick advances;
  tick changes state; 422 on out-of-range tick counts; all three disruption
  types; 422 on unknown type; 400 on bad target; same seed reproduces;
  versioned prefix.

### Automatic test results
**161 passed / 161** in 14.93 s (43 new).

Full-scale verification (the real SH.docx numbers):
- Build: 30 hubs, 200 vehicles, 5 000 shipments, 600 legs in **0.51 s**
- 120 ticks in **1.23 s** (~10 ms/tick)
- After 120 ticks: 226 DELIVERED, 1 006 IN_TRANSIT, 3 768 PENDING;
  legs 71 ARRIVED / 308 DEPARTED / 221 SCHEDULED
- Disruption injected: `Shipment S00000 marked MISPLACED`

### Errors encountered
1. **`alembic revision --autogenerate` failed:** *"Target database is not up to
   date."* Root cause: `sh205.db` had been recreated by `init_db()`
   (`create_all`) during Phase 3 manual testing, so the tables existed but the
   `alembic_version` marker did not match.
   *Fix:* deleted the database and rebuilt it through `alembic upgrade head`
   before autogenerating. **Operational note: prefer `alembic upgrade head`
   over letting `init_db()` create the schema when migrations matter.**
2. **`AttributeError: 'WorldSpec' object has no attribute '__dict__'`** — the
   dataclass uses `slots=True`.
   *Fix:* used `dataclasses.replace(SMALL, seed=99)`.
3. **`test_capacity_returns_when_the_shipment_alights` failed** — expected
   500.0, got 537.68. **Not a simulator bug.** Once the builder seeds initial
   itineraries, the chosen leg carries other shipments whose capacity also
   returns on arrival.
   *Fix:* the test now picks a leg with no other `shipment_links`, isolating
   the behaviour it actually asserts.

### Fixes applied
All three fixed and re-verified; suite green at 161/161.

### Final status
✅ All Phase 4 acceptance criteria met:
- simulator creates world ✅ (full scale, 0.51 s)
- tick changes state ✅ (asserted on leg-status fingerprint)
- disruption changes shipment state ✅ (all three disruption types)
- deterministic seed ✅ (identical worlds asserted)

### Remaining limitations / dependencies
- **No multi-hop itineraries yet.** The builder books only *direct*
  origin→destination legs, so ~75% of shipments stay `PENDING`. Multi-hop
  routing is E6's job (Phase 7) — this is the correct division of labour, not
  a gap.
- **No background tick loop.** Ticks are advanced by explicit API call, which
  is what the demo script needs. An automatic asyncio loop can be added in
  Phase 18 alongside WebSocket streaming.
- **Tick logging is INFO per tick.** Useful for the demo (visible activity),
  but noisy when advancing 100 ticks at once.
- **Vehicle position is hub-to-hub, not interpolated.** Vehicles jump to the
  destination hub on arrival rather than moving along the polyline. Adequate
  for the map until Phase 20 decides whether smooth movement is wanted.
- `ShipmentLeg` has no capacity double-booking guard beyond the unique
  `(shipment_id, leg_id)` constraint; E6 owns feasibility from Phase 7.

---

## PHASE 5 — E4 Adaptive Recovery Temperature

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
The SH.docx §16 temperature and lambda formulas, plus the four-way admin
policy dial that re-weights them.

    T(s)      = clamp(0, 100, T_base + T_time + T_delay + T_cascade)
    lambda(s) = sla_penalty_per_hour * (1 + T(s)/50)      [rupees/hour]

### Files created
| File | Purpose |
|---|---|
| `backend/app/engines/e4_temperature/engine.py` | Term functions, `compute_temperature`, `TemperatureEngine` |
| `backend/app/engines/e4_temperature/policy.py` | `PolicyWeights`, four modes, `get/set_policy` |
| `backend/tests/test_e4_temperature.py` | 37 tests |

### Important logic
- **Formulas quoted verbatim from §16**, with the citation in the docstring so
  the maths can be traced back to the spec.
- **T_time is deliberately non-linear** (squared closeness): urgency climbs
  slowly a day out and steeply in the final hours. A test asserts the late
  gain exceeds the early gain.
- **Every term saturates** — delay at 12 h, cascade at depth 5, priority at
  2.0 — so no single factor can dominate the clamp.
- **Full breakdown returned.** `TemperatureBreakdown` carries `t_base`,
  `t_time`, `t_delay`, `t_cascade` because E8 must explain *why* a shipment is
  hot, not just how hot. A test asserts the four terms sum to the temperature.
- **Customer premium raises lambda but NOT temperature** — SH.docx §4.4 is
  explicit that expedite payment is "an input, not an override". Asserted.
- **Four policy modes** re-weight the terms: BUSINESS (balanced), SLA_STRICT
  (deadlines dominate), FAIRNESS (waiting time dominates), EFFICIENCY
  (downstream impact dominates). Custom coefficients stored on the row
  override mode defaults, so an admin can tune without a new mode.

### Automatic tests performed / results
**37 passed / 37** in 0.99 s. Coverage: lambda at T=0/50/100 (base/double/
triple), lambda scaling and monotonicity; clamping at both ends; temperature
rising as deadline approaches; horizon cut-off; overdue saturation;
non-linearity; delay and cascade monotonicity and saturation; priority effect;
breakdown summation; customer premium isolation; zone banding (6 cases);
all four modes present; unknown mode fallback; **policy change alters output**;
SLA_STRICT reacts harder to deadlines than FAIRNESS; EFFICIENCY reacts harder
to cascade than SLA_STRICT; singleton policy row; persistence; unknown mode
rejected; custom weight override; corrupt JSON fallback; engine apply;
deadline sensitivity; policy change picked up; batch apply ordering.

### Errors encountered
None — 37/37 on first run.

### Final status
✅ All Phase 5 acceptance criteria met:
- temperature changes under controlled conditions ✅
- lambda changes correctly ✅ (asserted against §16 at three points)
- policy changes affect output ✅

### Remaining limitations / dependencies
- `T_cascade` reads `Shipment.cascade_depth`, which nothing writes until
  Phase 13. Until then it is always 0 — correct, but the term is untested
  against real cascade data.
- Policy weights are hand-tuned, not learned. Re-weighting from outcomes is
  E9's territory (Phase 15).
- No `/policy-mode` endpoint yet; that is Phase 17. The engine and persistence
  are ready for it.

---

## PHASE 6 — Recovery Pressure Score

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
The Recovery Pressure Score and Emergency Recovery Mode:

    P(s) = w_time*f_time + w_temp*f_temp + w_cascade*f_cascade + w_risk*f_risk
    weights sum to 1.0  =>  P(s) in [0, 1] by construction
    Emergency Recovery Mode when P(s) >= 0.75

### Files created
| File | Purpose |
|---|---|
| `backend/app/engines/e4_temperature/pressure.py` | Factors, `compute_pressure`, `evaluate_shipment`, `apply_pressure` |
| `backend/tests/test_pressure.py` | 44 tests |

### DOCUMENTED ASSUMPTION
Pressure appears in the finalized feature list but has **no formula in
SH.docx §16**, so the formula above is defined here rather than quoted. The
module docstring records this, along with why it is not a duplicate of
Temperature:

| | Temperature T(s) | Pressure P(s) |
|---|---|---|
| Range | 0–100 | 0–1 |
| Means | **business urgency** | **operational stress** |
| Feeds | lambda, i.e. pricing | search aggressiveness |
| Answers | "what is it worth spending?" | "how hard should we search, and should we stop being economical?" |

They genuinely differ: a valuable shipment with plenty of slack is hot but not
pressured; a cheap shipment that has failed three recovery attempts with two
hours left is under extreme pressure but never hot enough to justify a large
bounty on urgency alone.

### Important logic
- **Bounded by construction.** The four weights (0.40 time, 0.25 temperature,
  0.20 cascade, 0.15 risk) sum to exactly 1.0, and every factor is clamped to
  [0,1], so the score cannot leave [0,1]. A test asserts the weights sum to 1.
- **Failed attempts outweigh predictions** in `risk_factor` (0.6 vs 0.4): an
  attempt that actually failed is stronger evidence than a prior probability —
  which matters given E1's measured AUC of 0.4999 (see Phase 3).
- **Handles unscored shipments** — `p_misplace=None` contributes 0 rather than
  raising, since E1 scoring is asynchronous.
- **Full breakdown returned** for the Explainer; a test reconstructs the score
  from the published factors.

### Automatic tests performed / results
**44 passed / 44** in 0.45 s. Coverage: zero case; worst case exactly 1.0; a
21-combination parametrised bounds sweep; each factor's saturation and
linearity; failures-beat-predictions; unscored handling; **pressure changes
with time** (4-point ordering); responds to priority via temperature;
responds to cascade; responds to failed attempts; emergency off below /
on above threshold; flag tracks threshold exactly across 6 points; calm
shipment never triggers; breakdown reconstruction; weights sum to 1;
persisted-shipment evaluation and write-back; **pressure rises as simulated
time passes**; unscored shipment safe.

### Errors encountered
None — 44/44 on first run.

### Final status
✅ All Phase 6 acceptance criteria met:
- pressure score changes with time ✅
- pressure responds to priority/cascade ✅
- emergency threshold works ✅

### Remaining limitations / dependencies
- `failed_attempts` is a caller-supplied parameter; nothing counts real
  failures until E7 Graph Memory (Phase 8) records failed paths.
- `EMERGENCY_THRESHOLD = 0.75` is a judgement call, not a derived value.
  Easy to tune; worth revisiting once Phase 23 shows how often it fires.
- Nothing consumes `emergency` yet — E6 (Phase 7) is the first engine that
  will act on it by authorising dedicated vehicles.

### Suite status after Phases 5 and 6
**242 passed / 242** in 16.66 s.

---

## PHASE 7 — E6 Piggy Router ⛔ CRITICAL CHECKPOINT

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE — manual tests run and passed

### What was implemented
The core optimizer: a time-expanded transportation graph and a
Resource-Constrained Shortest Path solver using **label setting with
dominance pruning**, producing k-best recovery plans across the PIGGYBACK /
DEDICATED strategies.

Edge weight, quoted from SH.docx §16:

    w(e) = C_transit(e) + lambda(s) * transit_hours(e) + handling_penalty(e)

### Files created
| File | Purpose |
|---|---|
| `backend/app/engines/e6_piggy_router/graph.py` | `Edge`, `TransportGraph`, `build_graph`, transfer timing |
| `backend/app/engines/e6_piggy_router/router.py` | `PiggyRouter`, `_Label` + dominance, scoring, `dedicated_plan`, `route_shipment` |
| `backend/tests/test_e6_router.py` | 41 tests |

### Files modified
| File | Change |
|---|---|
| `backend/app/api/v1/routes/simulation.py` | Added `GET /simulate/route/{id}` — prototype-only E4+Pressure+E6 preview |
| `backend/app/schemas/simulation.py` | `RoutePreviewResponse` |

### Important logic
- **Three hard constraints enforced during expansion**, not after: capacity
  (kg and m³), deadline, and transfer count. A label that cannot lead to a
  feasible plan is never pushed onto the heap.
- **Dominance pruning at intermediate hubs only.** A label dominates another
  when it is no worse on cost, arrival and transfers, and strictly better on
  at least one. **Applying this at the destination too was a real bug** — the
  optimal plan dominated every alternative away and k-best returned exactly
  one plan. The destination now retains all arrivals (up to a cap), because
  k-best needs the alternatives and E8 needs them to explain rejections.
- **Minimum transfer time** of 30 minutes between legs; a 10-minute
  connection is correctly refused.
- **Transfer cap of 4** — each transfer is a physical handling risk, and
  unbounded transfers explode the search.
- **Geo pruning** via haversine (the PostGIS `ST_DWithin` stand-in, constraint C3).
- **Closed hubs and cancelled legs are excluded** from the graph at build time.
- **Scoring** blends cost (0.55), deadline slack (0.25) and transfer count
  (0.20), normalised against the worst candidate so scores are comparable
  within one call.
- **Rejection reasons are concrete strings**, never placeholders — E8 renders
  them verbatim. A test asserts no reason is empty or contains "TODO".

### Automatic tests performed
41 tests: edge-weight formula against §16; lambda sensitivity; direct and
multi-hop routing; cheapest-first ranking; k-best ordering and the k limit;
no-path / empty-graph / unknown-hub rejection; capacity by weight and by
volume, exact-fit acceptance, and choosing the dearer leg that actually fits;
deadline respected, exact-deadline acceptance, on-time preferred over cheaper-
but-late; transfer minimum connection time, too-tight connection refused,
sufficient connection used, transfer cap enforced; four dominance-logic tests
plus a search-bounding test (29 parallel edges → under 200 labels); dedicated
plan always available, can miss a tight deadline, offered on request;
**piggyback beats dedicated on cost**; dedicated wins when no piggyback
exists; every rejection carries a real reason; metrics reported; graph builds
from the database, excludes closed hubs, excludes cancelled legs; full
end-to-end `route_shipment`.

### Automatic test results
**283 passed / 283** in 16.63 s (41 new).

Full-scale engine check (30 hubs / 200 vehicles / 5 000 shipments / 600 legs):
- graph build: 600 edges, 30 hubs in **12 ms**
- routing: **avg 11 ms** over 10 runs (min 9, max 17)
- S00000 at T=78.2 (HOT), λ=₹641, pressure=0.596 → 4 plans, 25 labels

### Errors encountered
1. **k-best returned only one plan.** Root cause: dominance pruning was
   applied at the destination hub, so the optimal label dominated all
   alternatives before they could be collected.
   *Fix:* dominance now applies to intermediate hubs only; the destination
   retains all arriving labels up to the cap.
2. **Piggyback failure was silently unexplained** — found during *manual*
   testing, not by the unit tests. When the dedicated fallback succeeded, no
   rejection was recorded at all, so a dispatcher would see "DEDICATED chosen"
   with nothing saying why existing capacity could not be used. SH.docx §5.2
   requires exactly that explanation.
   *Fix:* a piggyback rejection is now always recorded when no piggyback plan
   survives, regardless of the dedicated outcome. Two regression tests added.
3. **A follow-up test asserted the wrong reason.** Late-arriving edges are
   pruned during expansion, so no label reaches the destination and the code
   returns NO_PATH rather than DEADLINE_MISSED. The pruning is correct; the
   NO_PATH *wording* was misleading ("within the planning horizon").
   *Fix:* reworded to "No route using existing capacity reaches the
   destination before the deadline", which is accurate for both causes, and
   corrected the test.

### Fixes applied
All three fixed and re-verified; suite green at 283/283.

### Final status
✅ All Phase 7 acceptance criteria met:
- feasible route generated ✅
- infeasible route rejected ✅ (with a concrete reason)
- capacity respected ✅ (weight and volume)
- deadline respected ✅
- k-best plans ✅

---

### MANUAL JURY TEST EXECUTION — PHASE 7

Run by Claude at the owner's request. Live server, clean database, full-scale
world (30 hubs / 200 vehicles / 5 000 shipments / 600 legs, seed 42).

| # | Test | Result | Evidence |
|---|---|---|---|
| 7.1 | World builds at full scale | ✅ PASS | `{"hubs":30,"vehicles":200,"shipments":5000,"legs":600,"seed":42}` |
| 7.2 | Disrupt → E4 → Pressure → E6 | ✅ PASS | S00000 T=78.2 **HOT**, λ=₹641, pressure=0.596 → 4 plans, 25 labels, 307 edges, 0.3 ms |
| 7.3 | Tight deadline rejects piggyback *with a reason* | ✅ PASS | S02777 → DEDICATED ₹11,421 + `REJECT PIGGYBACK: No route using existing capacity reaches the destination before the deadline` |
| 7.4 | Heaviest shipment still routes within capacity | ✅ PASS | S02770 (119.92 kg) → 3 plans, cheapest PIGGYBACK ₹111,785 |
| 7.5 | **Piggyback beats dedicated** (the core pitch) | ✅ PASS | PIGGYBACK ₹67,586 vs DEDICATED ₹106,549 — **₹38,963 saved, 36.6%**; winner PIGGYBACK |
| 7.6 | Routing latency at full scale | ✅ PASS | 15–53 ms end-to-end HTTP; engine compute **0.27 ms** |
| 7.7 | Unknown shipment | ✅ PASS | `404` |

**Test 7.3 is the one that earned its keep** — it exposed the missing
rejection explanation that the unit tests had not caught.

### How to reproduce these by hand

    cd C:\projects\CSH\backend
    .venv\Scripts\python.exe -m uvicorn app.main:app

    curl -X POST http://localhost:8000/simulate/reset -H "Content-Type: application/json" -d "{\"seed\":42,\"hub_count\":30,\"vehicle_count\":200,\"shipment_count\":5000,\"leg_count\":600}"
    curl -X POST http://localhost:8000/simulate/inject-disruption -H "Content-Type: application/json" -d "{\"type\":\"MISPLACE_SHIPMENT\"}"
    curl "http://localhost:8000/simulate/route/1?k=5"

*Expected:* a `plans` array, best-first, where a `PIGGYBACK` plan costs
materially less than the `DEDICATED` one, plus temperature and pressure
blocks. *Failure indication:* empty `plans`, `DEDICATED` ranked first when a
piggyback plan exists, or `rejected` entries with a null/empty `reason`.

All of this is clickable at <http://localhost:8000/docs>.

### Remaining limitations / dependencies
- **Cheap-but-slow can outrank fast-but-dear.** Cost is weighted 0.55 against
  slack 0.25, so the winning PIGGYBACK arrived 05-04 16:52 while DEDICATED
  would have arrived 05-02 19:50. Defensible (that is what "piggyback" means)
  but the weights are a judgement call — worth revisiting if the demo wants a
  more urgent-looking recommendation.
- **HYBRID strategy is not yet produced.** `PlanStrategy.HYBRID` exists in the
  schema; combining a piggyback prefix with a dedicated final leg is naturally
  Route Fusion's job (Phase 12).
- **Plans are not persisted.** `route_shipment` returns candidates but writes
  no `RecoveryPlan` rows. Persistence belongs with the Orchestrator (Phase 16).
- **No warm-start.** Every call searches from scratch; E7 Graph Memory
  (Phase 8) adds label reuse and failed-path memory.
- **Pressure/emergency is computed but not consumed.** E6 does not yet widen
  its search or force dedicated when `emergency` is true.
- **`GET /simulate/route/{id}` is prototype-only** and unauthenticated; the
  real planning endpoints and role guards arrive in Phases 17 and 19.

---

## PHASE 8 — E7 Graph Memory

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
Retained labels, failed-path memory, backtracking and warm-start, behind a
swappable cache interface (constraint C4: in-process LRU, not Redis).

### Files created
| File | Purpose |
|---|---|
| `backend/app/engines/e7_graph_memory/cache.py` | `MemoryCache` ABC + thread-safe `InProcessCache` (LRU, bounded) |
| `backend/app/engines/e7_graph_memory/memory.py` | `QueryKey`, `StoredPlan`, `GraphMemory` |
| `backend/app/engines/e7_graph_memory/planner.py` | `plan_recovery` (E6 + warm-start), `record_failure` |
| `backend/tests/test_e7_graph_memory.py` | 34 tests |

### Files modified
`backend/app/engines/e6_piggy_router/router.py` — `excluded_leg_ids` parameter
so known-failed legs are skipped during expansion.

### Important logic
- **Equivalence-class keying.** State is keyed by bucketed
  (origin, destination, weight, volume, urgency, lambda) rather than by
  shipment id, so two similar shipments reuse one answer. Weight and volume
  buckets round **down**, so a cached plan is never reused for a *heavier*
  shipment than the one it was computed for.
- **Dominance is deliberately NOT applied to stored plans.** This was a real
  bug: it discarded exactly the fallbacks backtracking needs. Dominance
  belongs to partial labels during search, where pruning makes RCSPP
  tractable; applying it to stored alternatives left a single plan, so a
  failure of that plan had nothing to fall back to. Distinct routes are now
  all retained, deduplicated and cheapest-first.
- **Failed legs and failed routes are tracked separately.** A failed route
  removes only that plan; a failed *leg* invalidates every plan using it.
- **Dedicated plans are never memorised** — their cost depends on departure
  time, so caching one would produce a stale number.

### Automatic tests performed / results
**34 passed / 34.** Cache round-trip, miss, delete/clear, LRU eviction, hit
and miss counters, zero-bound rejection; equivalence-key sharing and
separation across weight/route/urgency, round-down bucketing, negative-input
safety; storage and retrieval, infeasible plans excluded, alternatives
retained, deduplication, limit; failed-route memory, plan invalidation by
route and by leg, failed-leg reporting; backtracking offers the next
alternative, runs out cleanly, never re-offers a failed route; per-class
invalidation; singleton. Against the real router: cold search, **warm-start
hit with zero labels explored**, warm-start no slower than cold, warm-start
disableable, recorded failure changes the next plan, failed leg excluded from
the next search, dedicated not memorised.

### Errors encountered
**Dominance discarded backtracking alternatives** (5 failing tests). Root
cause and fix as described above.

### Final status
✅ Acceptance criteria met: failed route remembered ✅ · repeated bad path
avoided ✅ · alternative path found ✅ · warm-start works ✅

### Remaining limitations
- Warm-start returns *which legs*, not their current schedule; leg timings are
  re-read by the caller. Fine today because plans are not yet persisted.
- Memory is not invalidated when the world changes (a cancelled leg can still
  sit in a cached plan until it fails once). Phase 16 should invalidate on
  disruption.

---

## PHASE 9 — E5 Bounty Market

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
The reverse auction from SH.docx §16, with Vickrey (second-price) settlement:

    MaxBounty = min(lambda * delta_t_saved, C_dedicated - C_overhead)
    Payment   = min(second_lowest_bid, MaxBounty)

### Files created
`backend/app/engines/e5_bounty/market.py`, `backend/tests/test_e5_bounty.py` (30 tests).

### Important logic
- **Vickrey pricing is the answer to "won't carriers game this?"** A bidder's
  payment does not depend on their own bid, so bidding true cost is optimal.
  A test asserts exactly this: bidding 300 or bidding 10 both pay 500.
- **Sole bidder is paid the reserve (MaxBounty)**, not their own ask —
  standard reverse-Vickrey with a reserve. Paying their ask would make
  under-bidding costly and destroy truthfulness.
- **MaxBounty is double-capped**: by what the time saving is worth, and by
  what dedicated recovery would have cost minus overhead. A bounty can never
  exceed the cost of simply dispatching a truck.
- **Eligibility is proximity + capacity**, not a fleet-wide query — "already
  heading that way" is the whole premise.
- Third-party carriers bid higher margins than owned vehicles, which is what
  makes owned capacity preferable at equal distance.

### Automatic tests performed / results
**30 passed / 30.** MaxBounty takes the lower term, is capped by dedicated
cost, never negative, zero when no time is saved, rises with lambda; payment
is second-lowest, capped at MaxBounty, sole-bidder reserve, none on no bids,
order-independent, **independent of the winner's own bid**; eligibility
discovery, ordering by true cost, radius and capacity filtering; auction
opens OPEN, bids recorded, double-bid refused, negative bid refused, bidding
after the window refused, bidding on a closed auction refused; lowest bidder
wins at second price, winner flag set, payment capped on settlement, no-bid
auction closes cleanly, sole bidder wins at reserve; simulated bids stay
under MaxBounty and are deterministic; full run; persistence.

### Errors encountered
None after removing a leftover artifact in `compute_payment` (a dead
`if False else` branch) before the first test run.

### Final status
✅ Acceptance criteria met: auction opens ✅ · bids arrive ✅ · winner
selected ✅ · bounty calculation correct ✅

### Remaining limitations
- Bidders are simulated; real driver accept/decline arrives with the Driver
  app (Phase 21).
- No escalation ladder yet (SH.docx §4.3 "offer goes to next bidder") — the
  auction settles in one round.

---

## PHASE 10 — E2 Foresight Reservation

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
The critical-fractile buy rule from SH.docx §16:

    Buy  <=>  P(misplace) >= Premium / (Premium + C_dedicated - E[Bounty])

### Files created
`backend/app/engines/e2_foresight/reservation.py`,
`backend/tests/test_e2_foresight.py` (22 tests).

### Important logic
- **The threshold is 1.0 whenever the option saves nothing** (expected bounty
  at or above dedicated cost), which means "buy only at certainty" — i.e.
  never. That is the mathematically correct degenerate case and is tested.
- **A risk floor** (0.05) prevents buying thousands of near-worthless options.
- **Every decision carries a concrete reason string** for E8, covering all
  five paths (unscored, below floor, no saving, buy, don't buy).
- `premium_burn_ratio` implements the Foresight metric SH.docx §5.1 flags as
  the number sharp judges ask for.

### ⚠️ CALIBRATION WARNING (recorded in the module docstring)
This rule consumes `P(misplace)` **directly**, so it is only as good as E1's
calibration — and the bundled E1 has a measured test ROC-AUC of **0.4999**
and Brier **0.243** (Phase 3). The maths here is correct and independently
tested; the *inputs* are weak. This is the phase where the Phase 3 finding
actually bites, as predicted.

### Automatic tests performed / results
**22 passed / 22.** Threshold matches the formula, free option always taken,
threshold 1.0 when no saving and when bounty exceeds dedicated cost, rises
with premium, falls as saving grows, always in [0,1] across a 27-case sweep;
reservation above threshold, rejected below, boundary buys, unscored never
reserves, negligible risk never reserves, no-saving never reserves,
probability clamped, premium defaults to a rate, reasons always concrete,
higher risk more likely, dearer premium less likely; persisted-shipment
evaluation; premium burn ratio incl. divide-by-zero.

### Final status
✅ Acceptance criteria met: reservation occurs when the threshold condition is
met ✅ · reservation rejected otherwise ✅

### Remaining limitations
- No `Reservation` table yet (deferred from Phase 2); decisions are computed,
  not persisted. `GET /reservations` arrives in Phase 17.
- `expected_bounty` is supplied by the caller; wiring it to a real E5
  estimate is the Orchestrator's job (Phase 16).

---

## PHASE 11 — E3 Hub Emergence

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
`HubScore(L) = usage_count(L, 30d) x mean_risk(cell(L))` (SH.docx §16), grid
aggregation, candidate generation, savings estimation, and audited approval.

### Files created
`backend/app/engines/e3_hub_emergence/engine.py`,
`backend/tests/test_e3_hub_emergence.py` (30 tests).

### Important logic
- **Usage is counted at leg MIDPOINTS, not endpoints.** This was a real design
  flaw caught by a failing test: aggregating at destination hubs meant every
  candidate sat on top of an existing hub and was immediately rejected by the
  proximity guard, so **zero candidates were ever generated**. The midpoint of
  a heavily-used, risky corridor is precisely where a new transfer hub
  relieves the network — which is what the formula is meant to surface.
- **Proximity guard** (120 km) stops proposing hubs where the network already
  has coverage. Inactive hubs do not block candidates.
- **Savings estimation is one transparent multiplication**, not an opaque
  model, because judges ask how the number was derived.
- **Approval is audited** (SH.docx §12) and creates a real `Hub` with
  `is_emergent=True`, immediately usable by the router.

### Automatic tests performed / results
**30 passed / 30.** HubScore formula, high-use×high-risk beats either alone,
zero-risk scores zero, empty samples safe; grid cell bucketing incl. negative
coordinates and centre containment; ranking by score, under-used cells
dropped, savings scale with traffic and risk; proximity guard incl. inactive
hubs; aggregation over a real world, window filtering, mean-risk bounds;
candidate generation and persistence, ranking, limit, **no duplicates on
regeneration**, no-traffic case, savings attached; approval creates a hub,
writes an audit entry, hub is router-usable, double approval refused;
rejection audited and creates no hub.

### Errors encountered
**Zero candidates generated** — root cause and fix as described above
(endpoint vs midpoint aggregation).

### Final status
✅ Acceptance criteria met: high-risk/high-use area generates a candidate ✅ ·
low-risk area does not incorrectly dominate ✅ · approval updates the
database ✅

### Remaining limitations
- `mean_risk` depends on `p_misplace`, which inherits E1's weak calibration.
- Grid is a fixed 0.5° lattice; a clustering approach would place candidates
  more precisely.

---

## PHASE 12 — Route Fusion

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
Merging two recovery movements onto one vehicle when compatibility, capacity,
deadline and cost all permit.

### Files created
`backend/app/engines/e6_piggy_router/fusion.py`,
`backend/tests/test_route_fusion.py` (23 tests).

### Important logic
- **Four independent gates**, each with its own concrete rejection message:
  corridor compatibility (250 km endpoint match), combined capacity, deadline
  for *both* shipments, and a strict cost improvement.
- **A detour guard** (1.35x the longer leg) stops "merges" that wander.
- **Both pickup orderings are evaluated** and the cheaper is used.
- Reports `distance_saved_km` (the vehicle-km-avoided headline metric,
  SH.docx §5.1) and `utilisation_gain`.
- `fuse_all` is greedy, not optimal — exact matching is overkill at prototype
  scale, and this is stated in the docstring rather than implied.

### Automatic tests performed / results
**23 passed / 23.** Parallel corridors compatible, divergent and opposite
incompatible; compatible routes merge, incompatible stay separate, merging
reduces vehicle-km and cost, utilisation gain reported; over-weight and
over-volume refused, exact fit allowed; deadline miss refused with the
offending shipment named, tighter deadline governs; no-saving merge refused;
merged distance is order-independent and beats separate trips; every refusal
carries a concrete reason; batch pairing, each movement merged at most once,
nothing-compatible and empty-batch cases.

### Final status
✅ Acceptance criteria met: compatible routes merge ✅ · incompatible routes
remain separate ✅ · cost/utilisation metrics update ✅

### Remaining limitations
- Fusion operates on `Movement` objects, not persisted plans; wiring it into
  the plan pipeline is Phase 16.
- HYBRID strategy (piggyback prefix + dedicated tail) is still not produced.

---

## PHASE 13 — Recovery Cascade ⛔ CRITICAL CHECKPOINT

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE — manual tests run and passed

### What was implemented
Dependency-graph propagation of a disruption across shipments, vehicles and
hubs, with priority, temperature and pressure updates for everything
genuinely affected — and nothing else.

### Files created
`backend/app/engines/e4_temperature/cascade.py`,
`backend/tests/test_cascade.py` (25 tests).

### Files modified
`backend/app/api/v1/routes/simulation.py` — added
`POST /simulate/cascade/{origin_type}/{origin_id}` (prototype-only).

### Important logic — TERMINATION
Three **independent** guards make non-termination structurally impossible:
1. Every entity is visited **at most once** (a `visited` set). This alone
   bounds the work by entity count and would terminate even if the other two
   were deleted.
2. Propagation stops at `max_depth`.
3. Influence decays 0.55 per hop and stops below 0.05.

Proven live: `max_depth=500` on the full-scale world terminated at depth 5
after 2 635 iterations via influence decay. A deliberately **cyclic** graph
(hub0 → hub1 → hub0) is unit-tested and terminates.

### Important logic — proportional heat
`apply()` derives cascade depth from **influence**, not raw hop count:

    effective_depth = ceil(influence * CASCADE_SATURATION_DEPTH)

Hop count alone was badly misleading — see the defect below.

### Automatic tests performed / results
**25 passed / 25**; full suite **447 passed / 447**.

Propagation (vehicle → shipments, second hop, unrelated untouched, influence
decay and its rate, shipment- and hub-origin cascades, past legs excluded);
termination (terminates, max depth respected, depth-0 origin only, every
entity visited once, **cyclic graph terminates**, unknown origin);
application (cascade depth, temperature and pressure updated, depth raises
temperature, unaffected shipments keep their values, delivered shipments
skipped, idempotent depth, helpers, API serialisation with non-empty reasons);
plus two regression tests for the influence defect.

### Errors encountered
1. **First manual run showed an empty cascade.** Vehicle 1 simply had no
   upcoming legs — test selection, not a defect. Re-run against a
   cargo-carrying vehicle.
2. **`influence` was computed and then ignored when applying** — found by
   *manual* testing, not the unit tests. A shipment four hops out with
   influence 0.09 received `cascade_depth=4`, nearly saturating E4's cascade
   term, so a barely-connected shipment looked almost as urgent as a directly
   stranded one.
   *Fix:* effective depth now scales with influence. Two regression tests
   added. Verified live — see the table below.

### Fixes applied
Both resolved; suite green at 447/447.

### Final status
✅ Acceptance criteria met:
- one disruption affects downstream state ✅
- unaffected shipments remain unchanged ✅
- cascade cannot loop infinitely ✅ (three independent guards, proven live)

---

### MANUAL JURY TEST EXECUTION — PHASE 13

Run by Claude. Live server, clean database, full-scale world (seed 42),
20 ticks advanced.

| # | Test | Result | Evidence |
|---|---|---|---|
| 13.1 | Vehicle delay cascades downstream | ✅ PASS | Vehicle 181 → **1 334 affected** (1 252 shipments, 52 vehicles, 30 hubs), depth 4, 1 994 iterations |
| 13.2 | Blast radius by depth | ✅ PASS | depth 1: 29 · depth 2: 171 · depth 4: 968 |
| 13.3 | Depth limit contains the cascade | ✅ PASS | max_depth 1 → 26 shipments · 2 → 297 · 3 → 297 |
| 13.4 | **Termination under an absurd depth** | ✅ PASS | max_depth=**500** → terminated at depth 5, 2 635 iterations, *"influence decayed below threshold"* |
| 13.5 | Heat proportional to exposure (after fix) | ✅ PASS | see table |
| — | Unaffected shipments untouched | ✅ PASS | 3 748 shipments at T=0.0 |

**Test 13.5 — heat is now proportional to exposure:**

| cascade_depth | shipments | avg Temperature | avg Pressure |
|---|---|---|---|
| 3 (closest) | 29 | **26.6** | 0.227 |
| 2 | 212 | 18.7 | 0.127 |
| 1 (most distant) | 1 011 | 15.7 | 0.079 |
| 0 (untouched) | 3 748 | **0.0** | 0.0 |

Before the fix the distant 1 011 would have carried a near-saturated cascade
term. **Test 13.5 is the one that earned its keep.**

### How to reproduce by hand

    cd C:\projects\CSH\backend
    .venv\Scripts\python.exe -m uvicorn app.main:app

    curl -X POST http://localhost:8000/simulate/reset -H "Content-Type: application/json" -d "{\"seed\":42,\"hub_count\":30,\"vehicle_count\":200,\"shipment_count\":5000,\"leg_count\":600}"
    curl -X POST http://localhost:8000/simulate/tick -H "Content-Type: application/json" -d "{\"ticks\":20}"
    curl -X POST "http://localhost:8000/simulate/cascade/vehicle/181?max_depth=4"

*Expected:* `terminated_by` is non-empty, `total_affected` > 1, every
`shipments[].reason` is a real sentence, and `iterations` is bounded.
*Failure indication:* the request hangs (non-termination), `terminated_by` is
empty, or affected counts approach the whole fleet at low depth.

### Remaining limitations / dependencies
- **The blast radius is wide.** One truck delay touches ~25% of shipments at
  depth 4, because the hub → all-departing-shipments edge fans out hard. The
  influence weighting now makes the *heat* proportional, so this is
  defensible, but for the demo `max_depth=2` gives a tighter, more legible
  story (297 shipments rather than 1 252).
- **No re-planning trigger yet.** The cascade updates state but does not
  itself invoke E6; chaining that is the Orchestrator's job (Phase 16).
- **Cascade does not invalidate Graph Memory.** A cached plan using a
  now-delayed leg survives until it fails once. Should be wired in Phase 16.
- `POST /simulate/cascade/...` is prototype-only and unauthenticated.

### Suite status after Phases 8–13
**447 passed / 447** in 26.74 s.

---

## PHASE 14 — E8 Explainer

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
The counterfactual audit trail: what was chosen, what was rejected, and
concretely why — rendered as structured prose plus evidence, per SH.docx §5.2
("a readable card, not raw JSON").

### Files created
`backend/app/engines/e8_explainer/explainer.py`,
`backend/tests/test_e8_explainer.py` (26 tests).

### Important logic
- **Determinism is a hard rule.** Nothing samples, shuffles or reads the
  clock. A dispatcher reloading the page must see the same justification, and
  an audit trail that varies is not an audit trail. Tested three ways,
  including a sleep-then-recompute comparison.
- **No invented reasons.** A rejected plan with no recorded reason is
  reported as `MISSING_REASON`, which says explicitly that this indicates a
  *defect* — the explainer never manufactures a plausible-sounding excuse.
- **Two classes of alternative** are explained: plans the engine rejected
  (which carry a reason) and feasible plans that merely scored lower (for
  which a comparative reason is derived from cost, transfers or arrival).
- **The saving against dedicated recovery is quantified** in rupees and
  percent — the headline number for the pitch.
- **A late arrival is admitted, not hidden**: if the chosen plan misses the
  deadline the explanation says so and states by how much.

### Automatic tests performed / results
**26 passed / 26.** Determinism (identical dicts, identical prose across five
runs, independent of wall-clock); rejected candidates show actual reasons, no
placeholders anywhere, a missing reason is flagged as a defect, feasible
also-rans get comparative reasons, cheaper-but-slower explained by transfers,
cost delta reported, the chosen plan is not listed as its own alternative;
route evidence names real hubs and falls back safely, carries times and cost,
marks dedicated legs; piggyback and dedicated rationales, saving quantified,
slack stated, late arrival admitted, transfers described, lambda pricing
explained; urgency/market blocks populated, blocks empty when an engine did
not run, headline summary, JSON serialisation.

### Final status
✅ Acceptance criteria met: the selected-plan explanation is deterministic ✅ ·
rejected candidates show actual reasons ✅

---

## PHASE 15 — E9 Outcome Learning

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
Predicted-versus-actual capture for every recovery, persisted as training
records for a future retraining run.

### Files created
| File | Purpose |
|---|---|
| `backend/app/models/learning.py` | `RecoveryOutcome` table (16 tables total) |
| `backend/app/engines/e9_learning/outcomes.py` | Recording, error summary, training export |
| `backend/alembic/versions/c2d98f12f0a3_add_recovery_outcomes.py` | Migration |
| `backend/tests/test_e9_learning.py` | 29 tests |

### Important logic
- **E9 is strictly an observer.** It reads E1–E8 output and writes only to its
  own table. A test asserts recording does not mutate shipment status,
  temperature, lambda, pressure, risk or cascade depth — this is what keeps
  E9 an extension rather than a change to the documented architecture.
- **Per-observation Brier contribution** `(p - outcome)^2` is stored per row,
  so averaging the column gives E1's **live** Brier score. This is how the
  Phase 3 calibration concern becomes measurable in production rather than
  just a number from the training run.
- **Signed and absolute error are both reported.** A +100/-100 pair averages
  to zero but is not accurate; the summary reports both so that cannot hide.
- **Cost bias is classified** ("under-estimating" / "over-estimating" /
  "well calibrated") — the answer to "is the engine actually any good?".
- **Training export is plain dicts**, because SH.docx §10.1 keeps Colab
  decoupled: the handoff is data, not objects.

### Automatic tests performed / results
**29 passed / 29.** Brier contribution for confident-correct, confident-wrong,
coin-flip (exactly 0.25 — what an uninformative model scores) and unscored;
outcome recorded, cost error signed correctly both ways, ETA error in hours,
missing-time safety, prediction snapshot preserved, per-row Brier, deadline
hit and miss, failed recovery, recording from shipment state, undelivered
records a failure; summary of no data, aggregation, systematic under- and
over-estimation detection, absolute error does not cancel, live Brier score,
strategy filtering, deadline hit rate; training export as dicts, JSON
serialisable, limit respected, empty case; **E9 does not mutate engine state**.

### Final status
✅ Acceptance criteria met: recovery produces an outcome record ✅ ·
prediction error recorded correctly ✅

### Remaining limitations
- Nothing calls E9 automatically yet; the orchestrator produces the
  `PredictionSnapshot` and the recording happens when a recovery completes.
  Wiring that to delivery is Phase 18/23 work.

---

## PHASE 16 — Recovery Orchestrator ⛔ CRITICAL CHECKPOINT

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE — manual tests run and passed

### What was implemented
The full pipeline, chaining every engine:

    E1 -> E4 -> Pressure -> Cascade -> re-price -> E6+E7
       -> E2 -> E5 -> persist -> E8 -> (E9 snapshot)

### Files created
`backend/app/services/orchestrator.py`,
`backend/tests/test_orchestrator.py` (30 tests).

### Files modified
`backend/app/api/v1/routes/simulation.py` — `POST /simulate/recover/{id}`;
`backend/app/engines/e7_graph_memory/memory.py` — `StoredLeg` with hub ids;
`backend/app/engines/e7_graph_memory/planner.py` — faithful rehydration;
`backend/app/engines/e5_bounty/market.py` — marginal-cost bid model.

### Important logic
- **No engine logic lives in the orchestrator.** It sequences engines and
  persists their output; every formula stays in its own module.
- **A failing engine degrades the pipeline, it does not abort it.** Each stage
  is wrapped in a guard that records the failure, rolls the session back and
  continues. Proven by a test that injects an unavailable E1 and still gets a
  committed plan.
- **A plan is always produced.** If routing returns nothing, a dedicated
  fallback is synthesised — a recovery that returns nothing is worse than an
  expensive one.
- **Alternatives and rejections are persisted**, not just returned, so the
  Explainer survives a page reload and a dispatcher can override to a
  retained alternative.

### Automatic tests performed / results
**30 passed / 30**; full suite **537 passed / 537**.

Pipeline completeness and stage ordering, every engine contributes output;
persistence of committed plan, alternatives, ordered paths, exactly one
commitment, supersession, shipment status, rejected reasons; engine wiring
(risk, temperature, lambda, pressure written; explanation covers the plan and
carries every block; prediction snapshot feeds E9; full recover→deliver→record
loop); graceful degradation (unavailable E1, cascade skipped, auction
skipped, no-route fallback); timing, demo-speed budget, JSON serialisation.

### Errors encountered — four, three found by manual testing
1. **FOREIGN KEY constraint failed on `recovery_paths`** (24 tests failing).
   Root cause: E7 warm-start rehydrated plans with `from_hub_id=0` because
   `StoredPlan` never stored hub ids, so warm-started plans could not be
   persisted at all. *Fix:* added `StoredLeg` carrying hub ids and timings.
2. **One failed stage poisoned every later stage** with
   `PendingRollbackError` — the exact opposite of the "degrade, don't abort"
   guarantee the guard exists to provide. *Fix:* roll the session back on
   stage failure.
3. **The Explainer quoted pre-cascade figures.** `result.temperature` held
   T=11.2 while the shipment row held T=26.2, because cascade raises
   `cascade_depth` which feeds E4's T_cascade term. Two different numbers for
   the same shipment in one response. *Fix:* a "Re-price after cascade" stage.
4. **Re-planning left two COMMITTED plans for one shipment** — found by
   manual TEST 16.3. `_persist` superseded only PROPOSED plans, so the
   dispatcher would see two active recoveries. *Fix:* supersede COMMITTED
   plans too, with an explicit reason.

Plus a fifth, in E5, surfaced by the live pipeline (see below).

### The E5 zero-bounty defect — and the over-correction

**Symptom:** the live pipeline awarded a bounty of **₹0.00** on 5 bids.

**Root cause:** four vehicles parked *at* the pickup hub had `detour_km = 0`,
so `true_cost = 0` and they bid ₹0. Second-lowest was also ₹0.

**First fix (wrong):** include the full haul distance in the carrier's cost.
This made the next run award **nothing at all** — `NO_BIDS`. Carrier cost for
a ~1 000 km haul is ~₹25 000 against a MaxBounty of ₹8 207, so no bid could
ever clear.

**Why that was wrong:** it contradicts the premise of piggybacking. The
vehicle is *already* making that journey, so charging for the haul
double-counts work the carrier is doing anyway.

**Correct fix:** price the **marginal** cost — detour to pickup plus a
handling fee (loading, securing, scanning, unloading), floored at ₹100 so no
bid is ever free. `haul_km` is still reported for transparency but does not
enter the price.

**Result:** 5 bids, lowest ₹264.84, **paid the second-lowest ₹288.14**, well
under MaxBounty ₹8 206.67. Vickrey behaving exactly as specified.

### Final status
✅ Acceptance criterion met: **one recovery request executes the complete
pipeline** ✅

---

### MANUAL JURY TEST EXECUTION — PHASE 16

Live server, clean database, full-scale world (seed 42), 20 ticks,
**the real 205 MB E1 model loaded**.

| # | Test | Result | Evidence |
|---|---|---|---|
| 16.1 | Full pipeline, one request | ✅ PASS | S00001 → PIGGYBACK ₹40 778.81, **10/10 stages green, 448.9 ms** |
| 16.2 | Warm-start on repeat | ⚠️ PASS with caveat | Warm-start did **not** fire — see limitation below |
| 16.3 | Plans persisted | ✅ PASS (after fix) | 1 COMMITTED per shipment, 4 paths, 2 rejections with reasons |
| 16.4 | Explanation quality | ✅ PASS | 5 rationale lines, alternative explained, all 4 evidence blocks |
| — | Bounty is real money | ✅ PASS (after fix) | ₹288.14 paid, second-price, under MaxBounty |

**Stage timings (TEST 16.1), real E1:**

| Stage | ms | Detail |
|---|---|---|
| E1 misplacement | 121.26 | P(misplace)=0.4900 |
| E4 temperature | 3.76 | T=7.0 (COLD), λ=285.00 |
| Recovery pressure | 0.84 | pressure=0.047 |
| Recovery cascade | 288.90 | 602 affected, 551 updated, terminated by max depth |
| Re-price after cascade | 0.99 | **T=22.0, λ=360.00** |
| E6 router + E7 memory | 9.93 | 2 plans, 0 rejected |
| E2 foresight | 0.03 | reserve=True, threshold=0.131 |
| E5 bounty market | 14.97 | AWARDED, 5 bids, payment ₹288.14 |
| Persist plans | 4.97 | plan committed, 1 alternative retained |
| E8 explainer | 0.09 | 1 alternative explained |

**The Explainer output (TEST 16.4) — verbatim:**

> **S00001: PIGGYBACK recovery at 40778.81, arriving 2026-05-03T20:15**
> - Rides capacity already scheduled on this corridor, so no additional vehicle was dispatched.
> - Costs 40778.81 against 87354.77 for dedicated recovery, **a saving of 46575.96 (53.3%)**.
> - Arrives 2026-05-03T20:15, 22.8 hours inside the 2026-05-04T19:03 deadline.
> - Requires no transfers, minimising handling risk.
> - Priced at lambda = 360.00/hour from a temperature of 22.0 (COLD) under the BUSINESS policy.
>
> *Rejected:* DEDICATED @ 87354.77 — "Feasible but 46575.96 more expensive than the selected plan"

### How to reproduce by hand

    cd C:\projects\CSH\backend
    .venv\Scripts\python.exe -m uvicorn app.main:app
    # wait for: E1 loaded: misplacement_classifier v1

    curl -X POST http://localhost:8000/simulate/reset -H "Content-Type: application/json" -d "{\"seed\":42,\"hub_count\":30,\"vehicle_count\":200,\"shipment_count\":5000,\"leg_count\":600}"
    curl -X POST http://localhost:8000/simulate/tick -H "Content-Type: application/json" -d "{\"ticks\":20}"
    curl -X POST http://localhost:8000/simulate/inject-disruption -H "Content-Type: application/json" -d "{\"type\":\"MISPLACE_SHIPMENT\"}"
    curl -X POST "http://localhost:8000/simulate/recover/2?k=5"

*Expected:* `succeeded: true`, every entry in `stages` with `ok: true`, a
non-zero `explanation.market.payment`, and `why_chosen` containing a
quantified saving against dedicated recovery.
*Failure indication:* any stage `ok: false`; `payment` of 0 or null on an
AWARDED auction; `alternatives[].reason` empty; `total_ms` over ~2000.

### Remaining limitations / dependencies

1. **Warm-start rarely fires inside the orchestrator** (TEST 16.2). Each
   recovery re-prices the shipment, so λ moves into a different
   `lambda_bucket` and the E7 equivalence key changes — a cache miss. This is
   *defensible* (the shipment genuinely has different urgency the second
   time) but it undercuts the SH.docx §15 demo beat of a visibly faster
   warm-start re-plan. The E7 unit tests do exercise warm-start directly and
   pass. **Worth a decision before Phase 23**: widen the λ bucket, or key on
   pre-cascade λ.
2. **Cascade dominates the pipeline cost** — 289 ms of 449 ms. `max_depth=2`
   would cut it sharply and give a more legible demo story.
3. **E1 returned P=0.4900**, consistent with its measured AUC of 0.4999. The
   pipeline is correct; the signal is weak. Unchanged since Phase 3.
4. **Route Fusion is not yet in the pipeline.** It is implemented and tested
   (Phase 12) but operates on `Movement` objects; wiring it in needs multiple
   concurrent recoveries, which arrives with the batch flows in Phase 23.
5. **E9 recording is not automatic** — the orchestrator produces the
   `PredictionSnapshot`; recording happens when a recovery completes.
6. **Cascade still does not invalidate Graph Memory** (carried from Phase 13).
7. `POST /simulate/recover/...` is prototype-only and unauthenticated.

### Suite status after Phases 14–16
**537 passed / 537** in 35.50 s.

---

> **Owner sign-off, 2026-09-19:** Phases 14–16 manually verified by the owner
> ("all those phases i have verified manually as illustrated").

---

## PHASE 17 — REST API

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
The full documented endpoint map from SH.docx §9, plus a metrics endpoint for
the admin panel (§5.1). Response field names were chosen after reading the
frontend's `data.js`, so Phase 21 can swap the data source without
rewriting the UI.

| Group | Endpoints |
|---|---|
| Shipments | `GET /shipments` (status, temperature range, emergency filter, pagination; hottest first) · `GET /shipments/{id}` · `GET /shipments/{id}/recovery-plan` · `GET /shipments/{id}/explainer` · `POST /shipments/{id}/override` |
| Fleet | `GET /vehicles` · `GET /legs` · `GET /legs/{id}` (route-click panel, §6.2) · `GET /legs/{id}/bounty-status` |
| Hubs | `GET /hubs` · `POST /hubs` · `GET /hub-emergence/candidates` · `POST …/{id}/approve` · `POST …/{id}/reject` |
| Heatmap | `GET /heatmap?hour=` (HeatmapLayer-ready cells, §7) |
| Market | `GET /auctions` · `GET /auctions/{id}` · `POST /auctions/{id}/bid` · `POST /auctions/{id}/close` · `GET /reservations` · `GET /reservations/{id}` |
| Policy | `GET /policy-mode` · `PUT /policy-mode` |
| Metrics | `GET /metrics` |

Every route is also served under `/api/v1`.

### Files created
`app/schemas/api.py`, `app/services/presentation.py`,
`app/api/v1/routes/{shipments,fleet,hubs,market}.py`,
`tests/test_rest_api.py` (56 tests).

### Important logic
- **The explainer is rebuilt from the database**, not served from a cache,
  so it survives a restart and always matches what is actually committed.
- **Override is audited** (SH.docx §12). A rejected plan cannot be committed:
  the refusal returns its recorded rejection reason. The previously committed
  plan becomes `OVERRIDDEN` with the dispatcher's reason attached.
- **Policy change is audited** and returns the weights actually in force.
- **Heatmap falls back honestly.** If no legs depart in the requested hour, it
  aggregates resting shipments instead and says so in a `source` field,
  rather than returning an empty map without explanation.
- **Reservations are computed on demand.** There is still no Reservation
  table (deferred since Phase 2), so decisions are evaluated live.

### Automatic tests performed / results
**56 passed / 56.** List, sort, filter (status, temperature range),
pagination, limit validation, detail, 404; recovery-plan bundle and ordered
path; explainer rebuilt from DB, every alternative carries a reason,
deterministic, 404 without a plan; override switches the commitment and
writes an audit row, requires a reason, rejects a foreign plan; vehicles and
type filter; leg detail = info-panel payload incl. coordinates, aboard list
with temperature, 404, bounty status; hubs list, create, 409 on duplicate,
422 on bad coordinates; candidates generated and ranked, approval creates a
hub, double approval 409, unknown 404; heatmap cells bounded and sorted, 422
on hour 99, defaults to sim time; auctions list, bids cheapest-first, 404,
400 on bidding a closed auction, negative bid refused; reservations; policy
read/change, **policy change visibly affects temperature**, 400 on unknown
mode; metrics; six routes under `/api/v1`; **OpenAPI documents all 16 §9
paths**.

### Errors encountered
None. 56/56 on the first run.

### Final status
✅ Acceptance criteria met: endpoint tests ✅ · validation tests ✅ · error
handling tests ✅. **Authorization tests are deferred to Phase 19** because
they require Firebase, as the plan specifies.

### Remaining limitations
- **Every endpoint is currently open.** Role guards come in Phase 19.
- `vehicle_km_avoided` in `/metrics` is derived from transit-hour differences
  × 45 km/h. That is an approximation, and Phase 22 should replace it with
  real path distances.
- `AuditLog.actor_user_id` is null until Phase 19 identifies the caller.

---

## PHASE 18 — WebSocket / Realtime

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE

### What was implemented
`WS /ws/live` (SH.docx §9/§11) streams engine events to dashboards that stay
open. There is also a `GET /ws/stats` diagnostics endpoint.

**Event types:** `tick`, `shipment_update`, `vehicle_update`,
`temperature_update`, `pressure_update`, `plan_changed`, `auction_changed`,
`cascade_event`, `disruption`, `policy_changed`, `model_status`.

**Publishers wired:** simulator tick, all three disruption types,
orchestrator (plan, temperature, pressure, cascade, auction), policy change.

**Client protocol:** a `welcome` frame carrying recent history on connect,
`ping`→`pong`, `replay`, and structured `error` frames for bad input.

### Files created / modified
Created `app/services/events.py`, `app/api/v1/routes/realtime.py`,
`tests/test_realtime.py` (19 tests). Modified `app/workers/simulator.py`,
`app/services/orchestrator.py`, `app/api/v1/routes/market.py`,
`app/api/v1/router.py` and `app/main.py` to add publishers and bind the loop.

### Important logic
- **Publishing never raises.** An engine must not fail because nobody is
  listening or because a browser tab died. Dead clients are dropped rather
  than retried, so one stale socket cannot stall the tick loop.
- **Late joiners are not blank.** The last 50 events are replayed in the
  welcome frame, which matters when a juror's screen connects mid-demo.
- **One bad client cannot kill the server.** Malformed JSON gets an error
  frame and the socket stays usable. This is tested.

### Errors encountered
**1. Events from sync routes never reached any client (a real defect).**
FastAPI runs sync route handlers in a threadpool, where
`asyncio.get_running_loop()` raises. `publish()` treated that case as "no
loop" and wrote the event to history only. In effect **every tick,
disruption and plan change was silently not broadcast.** The WebSocket tests
would have blocked forever in `receive_text()` waiting for frames that were
never sent. This is the most likely reason the first test run stalled and had
to be interrupted.
*Fix:* the server loop is captured at startup (`bind_event_loop`), and
`publish()` hands events from worker threads to that loop with
`asyncio.run_coroutine_threadsafe`. `test_a_tick_reaches_a_connected_client`
acts as the regression test, since `/simulate/tick` is a threadpool route.

**2. A test could block indefinitely.** It read `receive_text()` in a loop
"until done", and that call has no timeout. *Fix:* the test now reads exactly
the three frames the orchestrator publishes first, in their known order.
All later test runs used a hard shell `timeout` so a hang cannot stall a
session again.

### Automatic tests performed / results
**19 passed / 19** in 3.5 s; full suite **612 passed / 612** in 35.1 s.
Event construction and serialisation; all documented types exist; publishing
without a loop is safe; welcome frame; ping/pong; replay; unknown type gives
an error; malformed JSON does not close the socket; **tick reaches a client**;
disruption reaches a client; policy change reaches a client; a recovery
emits `plan_changed` → `temperature_update` → `pressure_update` in order;
**two clients both receive the same tick**; reconnection; late joiner sees
history; stats; history bounded at 50; broadcasting with no clients is
harmless.

### Live verification against a real uvicorn process
This used a standalone `websockets` client instead of the in-process test
client. The world was full scale (seed 42).

| Trigger | Event received | Latency |
|---|---|---|
| `POST /simulate/tick` | `tick` | 97.5 ms |
| `POST /simulate/inject-disruption` | `disruption` | 30.1 ms |
| `PUT /policy-mode` | `policy_changed` | 37.7 ms |
| `POST /simulate/recover/69` | `plan_changed` → `temperature_update` → `pressure_update` → `cascade_event` → `auction_changed` | 1 898.9 ms* |

\* Dominated by the first E1 call while the 205 MB model was still loading.
Warm pipeline latency is ~450 ms (Phase 16).
`/ws/stats` after the run reported 9 events sent and 0 clients dropped.

### Final status
✅ Acceptance criteria met: a backend event reaches a connected client ✅.
"UI updates without page refresh" is satisfied at the transport level. The
page-side listener is Phase 21 work, because the existing frontend has no
WebSocket client yet.

### Remaining limitations
- **No automatic tick loop.** Ticks are still driven by API calls, which is
  what the demo script needs. A background loop can be added if wanted.
- **The WebSocket is unauthenticated** until Phase 19.
- `shipment_update` and `vehicle_update` are defined but not yet published
  per entity. Per-tick fan-out of 5 000 shipments would flood clients. The
  `tick` event carries the aggregate counts instead.

---

## PHASE 19 — Firebase Integration ⛔ CRITICAL CHECKPOINT

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE — automated and live read-only checks passed; valid-token round trip awaits owner

### What was implemented
Server-side Firebase authentication, role-based access control and Firestore
notifications, per SH.docx §3, §8.2, §11 and §12.

- **Token verification** on every data route (`Authorization: Bearer <ID token>`),
  via the Firebase Admin SDK and the existing service-account file, referenced
  **by path only**.
- **Roles from custom claims** (`admin | dispatcher | driver | customer`),
  re-verified on every request. The client's stated role is never trusted.
- **`require_role` guards** on every state-changing endpoint.
- **Audit entries now name the real actor** (`actor_user_id`).
- **WebSocket auth** via `?token=`, because browsers cannot set headers on a
  WS handshake.
- **Firestore notifications**: `/notifications/{uid}/items`,
  `/bounty_offers/{auction_id}` and `/live_positions/{vehicle_id}`.
  **Off by default.**
- **Role administration**: `POST /users/{uid}/role` (admin only, audited).

### Access matrix

| Route group | Required |
|---|---|
| `/health`, `/ready`, `/`, `/auth/status`, `/docs` | public |
| All reads (shipments, legs, vehicles, hubs, heatmap, metrics, auctions, reservations, policy, model status, `/auth/me`) | any verified user |
| `POST /shipments/{id}/override`, `POST /auctions/{id}/close`, `/simulate/*` demo controls | DISPATCHER |
| `POST /auctions/{id}/bid` | DRIVER |
| `PUT /policy-mode`, `POST /hubs`, hub-emergence approve/reject, `POST /model/reload`, `POST /simulate/reset`, `POST /users/{uid}/role` | ADMIN |
| `WS /ws/live` | any verified user (`?token=`) |

Admins pass every role check. SH.docx §3 describes the admin as the
superuser.

### Files created
| File | Purpose |
|---|---|
| `backend/app/core/security.py` | SDK init, token verification, `CurrentUser`, `get_current_user`, `require_role`, WS auth, `set_user_role` |
| `backend/app/services/notifications.py` | Firestore writers, gated and non-raising |
| `backend/app/api/v1/routes/auth.py` | `/auth/status`, `/auth/me`, `/users/{uid}/role` |
| `backend/scripts/get_id_token.py` | Owner helper: sign in, print an ID token |
| `backend/scripts/set_role.py` | Owner helper: assign a role claim |
| `backend/tests/test_auth.py` | 72 tests |

### Files modified
`app/core/config.py` (`auth_mode`, `firestore_enabled`,
`firebase_credentials_path`, production guard), `app/main.py` (non-fatal
Firebase init at startup), `app/api/v1/router.py` (router-level
authentication), role guards in `routes/{shipments,hubs,market,model,simulation,realtime}.py`,
`app/services/orchestrator.py` (Firestore bounty offers),
`app/models/enums.py` (`SET_USER_ROLE`), `tests/conftest.py`,
`tests/test_config.py`, `.env.example`, `requirements.txt`.

### Important logic
- **Least privilege by default.** A token with no role claim, or an
  unrecognised one such as `"superuser"`, maps to CUSTOMER. It is never
  escalated. This is tested.
- **The auth bypass cannot reach production.** `AUTH_MODE=disabled` together
  with `ENVIRONMENT=production` is refused by a settings validator at
  startup. The default is `firebase`.
- **Firebase failure degrades; it does not crash.** Missing or bad credentials
  leave the server running. Protected routes answer **503** with the reason,
  while `/health` stays green so a supervisor won't restart-loop it.
- **Precise 401s.** "Missing Authorization header", "must be 'Bearer <token>'",
  "token is invalid", "token has expired" and "token has been revoked" are
  each distinguished, and each 401 carries `WWW-Authenticate: Bearer`.
- **No live writes by default.** Firestore is gated by `FIRESTORE_ENABLED=false`.
  Every writer is a no-op returning False when disabled, and none of them
  ever raises, so a notification failure can never fail a recovery.
- **Bids never go through Firestore.** SH.docx §11 is explicit: Firestore is
  a read/notify channel, and transactional writes go through FastAPI.
- **User rows mirror claims** so audit entries can name a real actor. The
  Firebase claim remains the source of truth.

### Automatic tests performed
The token verifier is substituted with a deterministic fake, so **no test
contacts the live Firebase project**. Everything around verification runs
for real.

**72 tests:** public probes (4); auth status exposes no secrets; missing,
malformed (4 variants), invalid and expired tokens; valid token accepted;
`WWW-Authenticate` header; **13 data routes each reject an unauthenticated
call**; `/auth/me` role; no-role → CUSTOMER; **"superuser" claim not
escalated and blocked from admin routes**; user row synced; role matrices
for policy mode (4 roles), override (4), bidding (4), world reset (3), demo
controls (4), model reload (3) and hub admin (2); reads open to all four
roles; **audit entry records the real actor**; admin assigns a role (Firebase
call mocked) and it is audited; non-admin refused; unknown role → 422;
WebSocket without token refused, with a forged token refused, with a valid
token accepted; **missing credentials → 503 while `/health` stays 200**;
bypass refused in production; unknown `AUTH_MODE` refused; **enforcement is
the default**; dev bypass identifies itself; Firestore no-op when disabled;
notification and bounty offer written to the documented paths (fake client);
a failing Firestore never raises.

### Automatic test results
**72 passed / 72**; full suite **684 passed / 684** in 39.8 s.

### Live verification against the REAL Firebase project (read-only)
The server ran with the real service-account file. **Nothing was written to
the project and no users were created.**

| # | Check | Result |
|---|---|---|
| L19.1 | SDK initialises from the real credential file | ✅ `initialised: true`, project `maarg-36842` |
| L19.2 | `/health` public | ✅ 200 |
| L19.3 | `/shipments` with no token | ✅ 401 "Missing Authorization header" |
| L19.4 | Structurally valid but **forged JWT**, checked by the real Admin SDK | ✅ 401 "token is invalid" |
| L19.5 | Garbage token | ✅ 401 "token is invalid" |
| L19.6 | `PUT /policy-mode` with no token | ✅ 401 |
| L19.7 | WebSocket with no token / a forged token | ✅ handshake refused (HTTP 403) for both |
| — | Server log scanned for credential fragments | ✅ **0 found** |

Also confirmed: the backend's service account and the frontend's
`VITE_FIREBASE_PROJECT_ID` point at the **same** project, and
`backend/credentials/` is gitignored.

### Errors encountered
1. **A Phase 1 test began failing:** `Settings(environment="production")`.
   This was the new production guard working as intended, because the test
   environment sets `AUTH_MODE=disabled` and that combination is now refused.
   *Fix:* the test now states `auth_mode="firebase"` explicitly. The safety
   guard is correct and was left unchanged.
2. **WebSocket rejection was described inaccurately.** The docstring said
   unauthenticated sockets close with code 1008. Over a real network the
   handshake is refused with HTTP 403 instead; 1008 is only what the
   in-process test client reports. *Fix:* docstring corrected to describe
   both.
3. **Deprecation:** `datetime.utcnow()` in the notifier.
   *Fix:* replaced with `datetime.now(UTC)`.

### Final status
✅ Acceptance criteria:
- invalid token rejected ✅ (live, against the real SDK)
- role gate enforced ✅ (full matrix)
- protected endpoints ✅ (every data route, verified live)
- notification document written ✅ (to the documented path, against a fake
  client; the live write is gated off by design)
- **valid-token login round trip** ⏳ requires a real Firebase user, which only
  the owner can create (see manual tests below)

### ⚠️ Important operational change
**The API now requires a token by default.** The existing frontend does not
send one yet; that is Phase 21. Until then, for local demos, set this in
`backend/.env`:

    AUTH_MODE=disabled

The server logs a loud warning in this mode and refuses to start with it in
production.

### Remaining limitations
- Customers currently get the same read access as dispatchers. SH.docx does
  not specify customer-scoped filtering, such as "only my shipments". This is
  worth deciding before the Customer Portal (a stretch goal).
- No token-revocation check (`check_revoked=False`). Revocation would add a
  network call per request; the prototype accepts tokens until they expire
  (~1 h).
- Firestore has not been exercised live (it is gated off). Enabling it needs
  Firestore to be switched on in the Firebase console, plus
  `FIRESTORE_ENABLED=true`.

---

### MANUAL JURY TEST CASES — PHASE 19

These need **you**, because they create a user and write a role claim in your
Firebase project.

**One-time setup (≈3 minutes):**
1. Firebase console → **Authentication → Sign-in method** → enable **Email/Password**.
2. **Authentication → Users → Add user**: create `admin@maarg.test`, `dispatcher@maarg.test` and `driver@maarg.test` (any passwords).
3. Assign the roles (from `backend/`):

       .venv\Scripts\python.exe scripts\set_role.py admin@maarg.test admin
       .venv\Scripts\python.exe scripts\set_role.py dispatcher@maarg.test dispatcher
       .venv\Scripts\python.exe scripts\set_role.py driver@maarg.test driver

4. Make sure `AUTH_MODE` is **not** `disabled` in `backend/.env`, then start the backend:

       .venv\Scripts\python.exe -m uvicorn app.main:app

5. Get a token (the password is prompted and never echoed):

       .venv\Scripts\python.exe scripts\get_id_token.py dispatcher@maarg.test

   In PowerShell, keep it in a variable: `$T = .venv\Scripts\python.exe scripts\get_id_token.py dispatcher@maarg.test`

---

**TEST 19.1 — A real user logs in**
*Steps:* `curl http://localhost:8000/auth/me -H "Authorization: Bearer $T"`
*Expected:* `200` with your uid, email and `"role": "DISPATCHER"`, and `dev_bypass: false`.
*Failure indication:* `401 token is invalid`, meaning the token is from a different project or has expired (tokens last ~1 hour). `"role": "CUSTOMER"` means the role claim was not picked up; sign in again after running `set_role.py`.

**TEST 19.2 — No token, no data**
*Steps:* `curl http://localhost:8000/shipments`
*Expected:* `401 Missing Authorization header`.
*Failure indication:* `200` with data. That means auth is off; check `AUTH_MODE`.

**TEST 19.3 — The role gate holds**
*Steps:* with the **dispatcher** token:
`curl -X PUT http://localhost:8000/policy-mode -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "{\"mode\":\"SLA_STRICT\"}"`
*Expected:* `403 Role DISPATCHER is not permitted here; requires one of: ADMIN`.
Repeat with the **admin** token: expect `200`.
*Failure indication:* the dispatcher gets `200`.

**TEST 19.4 — The dispatcher can run the demo; the driver cannot**
*Steps:* `curl -X POST http://localhost:8000/simulate/tick -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "{\"ticks\":1}"`
with the dispatcher token, then with the driver token.
*Expected:* dispatcher `200`, driver `403`.

**TEST 19.5 — Actions are attributed**
*Steps:* change the policy mode with the **admin** token (19.3), then:

    .venv\Scripts\python.exe -c "import sqlite3;c=sqlite3.connect('sh205.db');print(c.execute('SELECT a.action,u.email,a.reason_text FROM audit_logs a JOIN users u ON u.id=a.actor_user_id ORDER BY a.id DESC LIMIT 1').fetchone())"

*Expected:* `('CHANGE_POLICY_MODE', 'admin@maarg.test', ...)`.
*Failure indication:* no row returned, which means the actor was not recorded.

**TEST 19.6 — A tampered token is rejected**
*Steps:* change one character in the middle of `$T` and repeat TEST 19.1.
*Expected:* `401 Authentication failed: token is invalid`.

**TEST 19.7 — Firestore notification (optional; writes to your project)**
*Steps:* enable Firestore in the console, set `FIRESTORE_ENABLED=true`,
restart the backend, run a recovery with the dispatcher token
(`POST /simulate/inject-disruption`, then `POST /simulate/recover/{id}`).
*Expected:* a document appears at **`bounty_offers/{auction_id}`** in the
Firestore console, with `status`, `max_bounty` and `payment`.
*Failure indication:* no document. Check the server log for
"Firestore write … failed".

---

> **Owner sign-off, 2026-09-19:** Phase 19 checkpoint acknowledged. Standing
> instruction from the owner for Phase 20 onward: use **only** the four
> existing test accounts (anita / rahul / suresh / meera `@maarg.demo`),
> create no Firebase users, request no console setup, and introduce no new
> authentication mechanism.

## FINDING — the four test accounts are not Firebase users (read-only check)

Before Phase 20 the existing Firebase setup was inspected, as instructed.
Nothing was created or modified.

| Check | Result |
|---|---|
| Where the four accounts are defined | `frontend/sidecar-site/js/session.js` (`ACCOUNTS`), with passwords checked **in the browser** |
| Does the frontend load the Firebase SDK? | **No.** No Firebase code in any page; `frontend/.env` is not read by the static site |
| `auth.get_user_by_email` for all four emails | **NOT FOUND** for all four |
| `auth.list_users` for project `maarg-36842` | **0 users** |
| Email/Password sign-in provider (Identity Toolkit config, GET) | **Enabled** — no console change is required |

**Consequence:** the four accounts have powered the *frontend's* demo login
all along, but they have never existed in Firebase Auth, so no Firebase ID
token can be issued for them. The Phase 19 backend verification is correct
(and was proven against the real SDK with forged tokens), but a valid-token
round trip for these accounts cannot happen until they exist as Firebase
users. Per the owner's instruction no user was created; this is carried to
the Phase 21 checkpoint as a single yes/no decision.

---

## PHASE 20 — Google Maps Integration

**Date:** 2026-09-19 · **Status:** ✅ COMPLETE (backend); browser rendering checks run in Phase 21

### What was implemented
The map layer of SH.docx §6–§7, built to feed the **existing** map code
(`gmaps.js` Google Maps with automatic Leaflet fallback, `map.js`,
`livemap.js`) without rewriting it. The frontend's rendering already handled
polylines, click-a-leg, the heat overlay, candidate pins and Directions;
what it lacked was real data.

| Endpoint | Purpose |
|---|---|
| `GET /map/network?hour=` | hubs (markers) + legs (polylines) + candidates (gold pins) + heat, in one call |
| `GET /map/heat?hour=` | heat points for the admin time-of-day slider (§7.1) |
| `GET /map/pickup-route/{auction_id}` | driver waypoints `[driver, pickup, destination]` for the Directions API (§6.3) |
| `GET /legs/{id}` (extended) | click panel now carries `path` + Google encoded `polyline` (§6.1) |

### Files created / modified
Created `app/services/geometry.py`, `app/services/mapdata.py`,
`app/api/v1/routes/map.py`, `tests/test_map.py` (27 tests).
Modified `app/schemas/api.py` (`LegDetail.path`, `.polyline`),
`app/services/presentation.py`, `app/workers/world.py` (polylines stored at
build), `app/api/v1/router.py` (map router, authenticated).

### Important logic
- **Payloads match `data.js` exactly.** Hubs `{id,name,lon,lat,base,dx,dy,a}`,
  legs `{id,veh,type,from,to,dep,arr,tot,res,rel,aboard,auction}`, candidates
  `{id,name,lon,lat,usage,risk,cost,save,status,score}` (money in ₹ lakh, as
  data.js uses), heat `{lat,lng,w,km}`. Tests assert each field set, so Phase
  21 is a data-source swap, not a UI rewrite.
- **Geometry identical to the existing map.** The server reproduces
  `map.js legPoints()` (quadratic Bézier, 28 segments, bend 0.13) — a test
  re-derives an interior point from the JS formula by hand — so the curves
  look exactly as before. Each leg is also stored as a **Google encoded
  polyline** (§6.1), and the encoder is verified against **Google's published
  reference example**.
- **The heatmap is real E1 output by hour.** §7 defines the heat as
  P(misplace) by (from_hub, to_hub, hour_of_day). `hour_of_day` is a genuine
  E1 feature, so every active leg is scored by the trained model at the
  requested hour; `congestion_index` is the leg's load factor. The slider
  therefore shows the model's actual response, not the Gaussian placeholder
  in data.js. Verified: 04:00 and 17:00 produce different hub risk.
- **Honest fallback.** Without E1 the heat falls back to stored shipment
  risk, and `source` says which was used.
- **Directions stay client-side**, as the existing `livemap.js` already
  calls `DirectionsService` with OSRM as fallback; the backend supplies
  waypoints plus a straight-line fallback polyline.

### Automatic tests performed / results
**27 passed / 27**; full suite **711 passed / 711**.
Polyline codec vs Google's reference (encode + decode), round trip on 40
Indian coordinates, empty case; curve endpoints, 29-point resolution, bend,
exact match to the JS formula, `point_along` clamping; polylines stored at
build, idempotent backfill; network payload layers; hub, leg, candidate and
heat field sets match data.js; legs reference existing hubs; path ↔ polyline
consistency; moving legs first; limit; **route-click panel carries the same
geometry**; honest fallback without E1; 422 on hour 24; pickup route 409
without a winner, 404 unknown, correct waypoint roles after a real recovery;
**E1 heat responds to the hour** (real model); stale-cache regression; cache
reuse for an unchanged world.

### Errors encountered
1. **Stale heatmap cache across worlds (real defect).** The cache key was
   `(hour, tick, leg count, max leg id)`. SQLite reuses row ids after a world
   rebuild, so a rebuild with a *different seed* but the same counts would
   have been served the previous world's risk.
   *Fix:* the key is now a hash of every E1 input the heat reads (route
   endpoints, load, vehicle, aboard count, departure). Two regression tests:
   a different-seed rebuild must re-score; an unchanged world must hit cache.
2. **Order-dependent test.** The "fallback without E1" test passed alone but
   failed in the full suite, because earlier suites leave the shared E1
   registry loaded. *Fix:* the test now injects an explicitly unloaded
   registry.
3. `leg_detail` computed geometry twice. *Fix:* computed once.

### Final status
✅ Route geometry, polylines, route info, markers, heatmap and directions
waypoints delivered and tested. "Map renders" and "fallback works when the
Maps API is unavailable" are browser checks, executed in Phase 21.

### Remaining limitations
- Leg geometry is the stylised arc the existing map draws, not road
  geometry. Road geometry already exists client-side for the live shipment
  view (Google Directions → OSRM fallback).
- Heat inherits E1's weak signal (test ROC-AUC 0.4999, Phase 3): it is the
  model's real output, but not a strong predictor.
