# 🧭 Maarg

### Adaptive AI-Powered Reverse Logistics & Recovery Optimization

**Maarg** is an intelligent logistics optimization platform designed to make returned, damaged, misplaced, or end-of-life products economically and environmentally recoverable.

Instead of treating reverse logistics as a simple **A → B routing problem**, Maarg continuously evaluates the entire recovery network and searches for better paths, consolidation opportunities, recovery strategies, and fallback decisions as conditions change.

> **Don't just route the package. Find the best future for it.**

🌐 **Live Platform:** https://maarg-three.vercel.app/

---

## Project Context & Contributions

Maarg was developed collaboratively as a **college hackathon team project**. This repository is my independent portfolio copy of that team project; it does not claim that I created or own the whole platform.

**My individual contribution:** I developed the complete [`e1-model/softHack/`](e1-model/softHack/) folder, including its ML data-audit and leakage checks, feature pipeline, model training and evaluation, inference code, and tests.

The rest of Maarg was developed collaboratively by the team. The original team repository is [SathwikPrabhu-07/Maarg](https://github.com/SathwikPrabhu-07/Maarg).

---

## 🚀 What Makes Maarg Different?

Traditional logistics systems usually answer:

> **"How do I move this package from here to there?"**

Maarg asks a different question:

> **"Given the package's condition, value, transportation cost, recovery possibilities, environmental impact, and changing network conditions, what should happen to it next?"**

A returned product may have multiple possible futures:

```text
                    ┌── Resell
                    │
                    ├── Refurbish
                    │
Returned Product ───┼── Repair
                    │
                    ├── Recycle
                    │
                    └── Dispose
```

Maarg dynamically evaluates these possibilities while considering:

* Recovery value
* Transportation cost
* Processing cost
* Product condition
* Demand
* Route availability
* Environmental impact
* Risk
* Network capacity
* Historical route performance

The result is a **dynamic recovery decision system**, not just a route planner.

---

# 🧠 Core Intelligence

## 1. 🌡️ Adaptive Temperature Engine

Maarg introduces an **Adaptive Temperature** mechanism that controls how aggressively the optimizer explores alternative recovery paths.

Instead of always choosing the currently highest-scoring option, the system can increase exploration when uncertainty or potential upside is high.

Conceptually:

```text
Final Score
    =
Base Recovery Score
+
Temperature × Exploration Bonus
```

Where the exploration bonus can incorporate:

```text
Potential Upside × Uncertainty
```

### Low Temperature

The system becomes more conservative.

```text
Known profitable path
        ↓
Choose reliable option
```

### High Temperature

The system becomes more exploratory.

```text
Known path
   +
Alternative paths
   +
Potential recovery value
   +
Uncertainty
        ↓
Explore better possibilities
```

This allows Maarg to adapt its decision-making behaviour instead of following a permanently fixed optimization policy.

---

# 🐷 2. Piggy Routing

### Don't send an empty vehicle when another shipment is already going there.

**Piggy Routing** identifies compatible shipments that can share an existing movement.

For example:

```text
Shipment A
Warehouse ───────────────► Hub B

Shipment B
Warehouse ───────────────► Hub B
```

Instead of treating them as completely independent movements:

```text
Shipment A ──┐
             ├── Shared Movement ──► Hub B
Shipment B ──┘
```

Maarg evaluates opportunities to piggyback compatible recovery shipments on existing routes.

This can reduce:

* Transportation cost
* Empty vehicle movement
* Duplicate trips
* Delivery distance
* Carbon impact

---

# 🧠 3. Graph Memory Engine

The logistics network is represented as a continuously evolving graph.

```text
Nodes
 ├── Warehouses
 ├── Hubs
 ├── Repair Centres
 ├── Refurbishment Centres
 ├── Recycling Facilities
 └── Customers

Edges
 ├── Routes
 ├── Cost
 ├── Distance
 ├── Time
 ├── Capacity
 ├── Reliability
 └── Historical Performance
```

But Maarg doesn't only remember where a package **is**.

It remembers the paths the package has already explored.

For example:

```text
A → B → C → D
      ↓
      X Failed

Graph Memory
      ↓
Backtrack
      ↓
A → B → E → F
          ↓
       Better option
```

If a route becomes infeasible, unprofitable, overloaded, or unreliable, the system can use its accumulated graph state to explore alternative paths rather than blindly restarting the entire decision process.

### The idea

> **Every failed path becomes information for the next decision.**

---

# 🔀 4. Route Fusion Engine

Piggy Routing handles individual compatible shipment opportunities.

**Route Fusion** operates at a broader level.

It continuously looks for persistent route overlap and determines whether multiple movements can be consolidated into a more efficient movement structure.

```text
Route A ────────┐
                │
Route B ────────┼──► Fused Route
                │
Route C ────────┘
```

The engine evaluates:

* Overlapping paths
* Timing compatibility
* Capacity
* Destination compatibility
* Cost savings
* Recovery deadlines
* Network constraints

Instead of optimizing shipments independently, Maarg can reason about the **network as a whole**.

---

# ♻️ 5. Recovery Optimization

A returned product doesn't automatically belong in a warehouse.

Maarg evaluates potential recovery strategies:

```text
                ┌── Resale
                │
                ├── Refurbish
                │
Product ────────┼── Repair
                │
                ├── Recycle
                │
                └── Dispose
```

Each strategy can be evaluated against multiple dimensions:

| Factor            | Consideration              |
| ----------------- | -------------------------- |
| Product Condition | Can it be recovered?       |
| Recovery Value    | Potential economic return  |
| Transport Cost    | Cost of reaching facility  |
| Processing Cost   | Cost of recovery           |
| Demand            | Probability of future sale |
| Risk              | Uncertainty of recovery    |
| Sustainability    | Environmental impact       |
| Time              | Recovery deadline          |

The system therefore optimizes for **recovery outcome**, not merely transportation distance.

---

# 🕸️ 6. Dynamic Recovery Graph

Maarg combines routing and recovery decisions into a connected decision graph.

A package can move through:

```text
Return
  ↓
Inspection
  ↓
Condition Assessment
  ↓
Recovery Decision
  ├── Resell
  ├── Repair
  ├── Refurbish
  ├── Recycle
  └── Dispose
```

Each decision can lead to a new network state.

That allows Maarg to reason about:

> **Where should the product go next?**

and also:

> **What should happen to the product after it gets there?**

---

# 🤖 AI-Driven Decision Layer

Maarg is designed around a combination of optimization, machine learning, graph reasoning, and intelligent orchestration.

The architecture can incorporate models for:

### Condition Assessment

Estimate the recoverability of returned products based on their condition.

### Recovery Value Prediction

Estimate potential value generated by different recovery strategies.

### Cost Prediction

Estimate transportation and processing costs.

### Demand Forecasting

Estimate whether recovered products are likely to have future demand.

### Risk & Sustainability Analysis

Evaluate uncertainty and environmental impact associated with recovery decisions.

---

# 🏗️ System Architecture

```text
                         ┌─────────────────────┐
                         │      Frontend       │
                         │   Next.js / Web UI  │
                         └──────────┬──────────┘
                                    │
                                    │ HTTPS
                                    ▼
                         ┌─────────────────────┐
                         │       Render        │
                         │   FastAPI Backend   │
                         └──────────┬──────────┘
                                    │
               ┌────────────────────┼────────────────────┐
               │                    │                    │
               ▼                    ▼                    ▼
       ┌──────────────┐     ┌──────────────┐    ┌──────────────┐
       │ PostgreSQL   │     │ Firebase     │    │ AI / ML      │
       │ Database     │     │ Auth         │    │ Decision     │
       └──────────────┘     └──────────────┘    └──────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Recovery Decision  │
                         │      Engine         │
                         └──────────┬──────────┘
                                    │
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
        Adaptive Temp.       Graph Memory        Route Fusion
                │                   │                   │
                └───────────────────┼───────────────────┘
                                    ▼
                            Optimal Recovery
                                 Path
```

---

# 🧩 Technology Stack

## Frontend

* Next.js
* React
* TypeScript
* HTML / CSS
* Vercel

## Backend

* Python
* FastAPI
* Uvicorn
* Render

## Database

* PostgreSQL

## Authentication

* Firebase Authentication
* Firebase Admin SDK

## AI / ML

* Machine Learning models
* Optimization algorithms
* Graph-based reasoning
* Adaptive decision mechanisms
* Recovery scoring

## Maps & Visualization

* Leaflet
* Google Maps API

---

# 🔐 Authentication & Security

Maarg uses Firebase Authentication for user identity and backend authorization.

The backend validates authenticated requests before allowing protected operations.

Production secrets are kept outside the source code through environment variables.

Examples include:

```text
DATABASE_URL
FIREBASE_CREDENTIALS_JSON
FIREBASE_API_KEY
FIREBASE_AUTH_DOMAIN
FIREBASE_PROJECT_ID
FIREBASE_APP_ID
CORS_ORIGINS
```

Sensitive credentials should never be committed to Git.

The frontend sidecar also contains mock demo accounts for its prototype login
flow. Those sample values are public, client-side demo data—not production
credentials—and the browser-only demo login is not a security boundary.

---

# 🌍 Production Deployment

Maarg is deployed using a separated frontend/backend architecture.

```text
GitHub
   │
   ├──────────────► Vercel
   │                 │
   │                 │ Frontend
   │                 ▼
   │            maarg-three.vercel.app
   │
   └──────────────► Render
                     │
                     │ FastAPI Backend
                     ▼
                Production API
```

### Frontend

Hosted on:

**Vercel**

### Backend

Hosted on:

**Render**

### Database

**PostgreSQL**

### Authentication

**Firebase**

---

# ⚙️ Local Development

## Clone the repository

```bash
git clone https://github.com/SathwikPrabhu-07/Maarg.git
cd Maarg
```

---

## Backend

```bash
cd backend
```

Create a virtual environment:

### Windows

```bash
python -m venv .venv
```

Activate:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure your environment variables in:

```text
backend/.env
```

Run the backend:

```bash
uvicorn app.main:app --reload
```

Backend:

```text
http://localhost:8000
```

Swagger:

```text
http://localhost:8000/docs
```

Health check:

```text
http://localhost:8000/health
```

---

# 💻 Frontend

```bash
cd frontend
```

Install dependencies if required:

```bash
npm install
```

Configure:

```text
frontend/.env
```

Set the API URL:

```env
MAARG_API_BASE_URL=http://localhost:8000
```

Run the frontend:

```bash
npm run dev
```

---

# 🔑 Environment Variables

## Backend

```env
DATABASE_URL=
ENVIRONMENT=development
DEBUG=true
LOG_JSON=false

AUTH_MODE=firebase

FIREBASE_CREDENTIALS_JSON=
FIREBASE_API_KEY=
FIREBASE_AUTH_DOMAIN=
FIREBASE_PROJECT_ID=
FIREBASE_APP_ID=

CORS_ORIGINS=http://localhost:3000
CORS_ORIGIN_REGEX=

FIRESTORE_ENABLED=false
```

## Frontend

```env
MAARG_API_BASE_URL=http://localhost:8000
MAARG_GOOGLE_MAPS_API_KEY=
```

Never commit real credentials.

---

# 📡 API

The FastAPI backend exposes an interactive API documentation interface.

Once the backend is running:

```text
/docs
```

For production:

```text
https://<your-render-service>.onrender.com/docs
```

Health:

```text
/health
```

Readiness:

```text
/ready
```

Simulation:

```text
POST /simulate/reset
```

The simulation environment allows the system to initialise and demonstrate its dynamic logistics network.

---

# 🧪 Simulation

Maarg includes a simulated logistics environment for demonstrating how the decision engine reacts to changing network conditions.

The system can represent:

```text
Orders
   ↓
Locations
   ↓
Routes
   ↓
Facilities
   ↓
Recovery Options
   ↓
Dynamic Decisions
```

The simulation provides a controlled environment for observing:

* Route changes
* Recovery decisions
* Network state
* Alternative paths
* Route fusion
* Shipment movement
* Optimization behaviour

---

# 📊 Decision Flow

A simplified Maarg decision cycle looks like this:

```text
Incoming / Returned Product
          ↓
Condition & Context
          ↓
Generate Candidate Paths
          ↓
Evaluate Recovery Strategies
          ↓
Calculate Cost / Value / Risk
          ↓
Apply Adaptive Temperature
          ↓
Check Graph Memory
          ↓
Search Alternative Paths
          ↓
Detect Piggy Routing Opportunities
          ↓
Detect Persistent Route Overlap
          ↓
Apply Route Fusion
          ↓
Select Recovery Path
          ↓
Execute / Simulate
          ↓
Store Outcome
          ↓
Update Graph Memory
```

This creates a feedback loop:

```text
Decision
   ↓
Outcome
   ↓
Memory
   ↓
Learning
   ↓
Better Future Decisions
```

---

# 🌱 Sustainability

Reverse logistics can create unnecessary transportation and processing when recovery decisions are made independently.

Maarg incorporates sustainability into the recovery decision rather than treating it as an afterthought.

Potential impact areas include:

* Reduced unnecessary transportation
* Shipment consolidation
* Better recovery utilisation
* Reduced empty movement
* Increased reuse and refurbishment
* More informed recycling decisions
* Reduced waste from premature disposal

The system can therefore consider economic and environmental objectives together.

---

# 🎯 Problem Maarg Targets

Modern supply chains deal with products that are:

* Returned
* Damaged
* Defective
* Over-stocked
* Misrouted
* Near end-of-life
* Economically recoverable
* Suitable for refurbishment or recycling

The challenge isn't simply moving these products.

The challenge is deciding:

> **What is the most useful thing that can happen to this product next?**

Maarg is built around that decision.

---

# 🔥 The Bigger Idea

Maarg treats reverse logistics as a **living decision graph**.

A route isn't permanent.

A recovery strategy isn't permanent.

A failed decision isn't wasted information.

A shipment doesn't always need its own journey.

And the closest facility isn't always the best destination.

Instead:

```text
                    MAARG
                      │
        ┌─────────────┼─────────────┐
        │             │             │
    Explore        Remember       Combine
        │             │             │
 Adaptive Temp.   Graph Memory   Route Fusion
        │             │             │
        └─────────────┼─────────────┘
                      │
                 Recover Better
```

---

# 🛣️ Roadmap

### Phase 1

* [x] Backend API
* [x] Frontend dashboard
* [x] Firebase authentication
* [x] PostgreSQL integration
* [x] Production deployment
* [x] Logistics simulation
* [x] Dynamic routing concepts

### Phase 2

* [x] Adaptive Temperature
* [x] Piggy Routing
* [x] Graph Memory
* [x] Route Fusion
* [x] Recovery Optimization

### Phase 3

* [ ] Advanced demand forecasting
* [ ] Real-world recovery facility data
* [ ] Automated carrier integration
* [ ] More advanced ML-based recovery scoring
* [ ] Multi-objective optimization
* [ ] Real-time logistics data integration
* [ ] Large-scale network simulation

---

# 🧑‍💻 Project Structure

```text
Maarg/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   └── ...
│   │
│   ├── scripts/
│   ├── requirements.txt
│   └── ...
│
├── frontend/
│   ├── ...
│   └── ...
│
├── render.yaml
├── vercel.json
├── README.md
└── .gitignore
```

---

# 🛡️ Production Notes

Before deploying:

```bash
git status
```

Make sure the following are **never committed**:

```text
.env
.env.local
firebase-credentials.json
*.db
credentials/
service-account.json
private keys
API keys
```

Use environment variables for all production secrets.

---

# 📈 Live Application

### Maarg

**https://maarg-three.vercel.app/**

The production frontend communicates with the FastAPI backend hosted on Render.

---

# ⭐ Why Maarg?

Most logistics systems optimise movement.

**Maarg optimises decisions.**

It combines:

```text
AI
+
Optimization
+
Graph Memory
+
Adaptive Exploration
+
Shipment Consolidation
+
Recovery Intelligence
```

to create a logistics system that can continuously reconsider what should happen next.

> **Maarg doesn't just find a route.
> It searches for a better outcome.**
