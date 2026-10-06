/* Architecture page */
/* ---------- Architecture ---------- */
function architecture(root) {
  const N = (t, s, hl) => `<div class="node${hl ? " hl" : ""}">${t}${s ? `<small>${s}</small>` : ""}</div>`;
  root.innerHTML = `<div class="wrap" style="padding-top:16px">${navHTML()}
    <div style="padding:56px 0 30px;max-width:800px"><p class="eyebrow">How it fits together</p><h1 class="h-section" style="margin:10px 0 14px;font-size:clamp(44px,6vw,80px)">Architecture</h1><p class="lead">Four layers: clients, API and realtime, the core engine with ML, and data. Google Colab trains models offline and is never part of the request path.</p></div>
    <div class="arch">
      <div class="layer"><h3>Client apps<small>React + TypeScript</small></h3><div class="nodes">${N("Admin dashboard")}${N("Dispatcher console")}${N("Driver app", "mobile web")}${N("Customer portal", "stretch")}</div></div>
      <div class="wire">HTTPS / WSS</div>
      <div class="layer"><h3>Edge & realtime<small>gateway and auth</small></h3><div class="nodes">${N("FastAPI REST + WebSocket gateway")}${N("Firebase Auth", "roles as custom claims")}${N("Firestore", "live state, push to clients")}</div></div>
      <div class="wire">tick events</div>
      <div class="layer"><h3>Core engine<small>FastAPI, Python 3.11</small></h3><div class="nodes">${N("Simulation clock / tick loop")}${N("E2 Foresight reservation")}${N("E3 Hub emergence")}${N("E4 Temperature / λ")}${N("E5 Bounty market")}${N("E6 Piggy router", "RCSPP", 1)}${N("E7 Graph memory", "warm start")}${N("E8 Explainer")}</div></div>
      <div class="layer"><h3>ML inference<small>loads exported artifacts</small></h3><div class="nodes">${N("E1 Misplacement classifier", ".pkl / .onnx", 1)}${N("Model registry", "versioned artifacts")}</div></div>
      <div class="layer"><h3>Data<small>source of truth</small></h3><div class="nodes">${N("PostgreSQL + PostGIS", "shipments, vehicles, hubs, legs, audit")}${N("Redis", "graph-memory label cache")}${N("Firestore", "positions, notifications, offers")}${N("Cloud Storage", "model artifacts, GeoJSON")}</div></div>
      <div class="layer"><h3>Map layer<small>front-end only</small></h3><div class="nodes">${N("Google Maps JS API", "base map, polylines")}${N("Directions API", "road routes, turn-by-turn")}${N("Canvas heat overlay", "risk layer")}${N("Leaflet + Esri tiles", "automatic fallback")}</div></div>
    </div>

    <section class="block" id="ml" style="padding-bottom:0"><div class="sec-head"><h2 class="h-section">Colab to backend</h2><p>Training stays in Colab. The only contract with production is two exported files.</p></div>
      <div class="flow"><div><b>1 · Train</b>Colab notebook builds the E1 classifier on synthetic history.</div><div><b>2 · Export</b><code>model.pkl</code> and <code>feature_pipeline.joblib</code>.</div><div><b>3 · Upload</b>Versioned path in Firebase Storage or GCS.</div><div><b>4 · Register</b>A ModelArtifact row marks vN as available.</div><div><b>5 · Hot-swap</b><code>POST /model/reload</code> loads the new version. No redeploy.</div></div></section>

    <section class="block" style="padding-bottom:0"><div class="sec-head"><h2 class="h-section">Formula sheet</h2></div>
      <div class="formulas"><div><small>Temperature</small><code>T(s) = clamp(0, 100, T_base + T_time + T_delay + T_cascade)</code></div><div><small>Urgency</small><code>λ(s) = sla_penalty_per_hour × (1 + T(s)/50)</code></div><div><small>Bounty</small><code>MaxBounty = min(λ × Δt_saved, C_dedicated − C_overhead)</code></div><div><small>Payment (Vickrey)</small><code>Payment = min(second_lowest_bid, MaxBounty)</code></div><div><small>Router edge weight</small><code>w(e) = C_transit(e) + λ × transit_hours(e) + handling_penalty(e)</code></div><div><small>Foresight</small><code>Buy ⟺ P(misplace) ≥ Premium / (Premium + C_dedicated − E[Bounty])</code></div><div><small>Hub emergence</small><code>HubScore(L) = usage_count(L, 30d) × mean_risk(cell(L))</code></div></div></section>

    <section class="block"><div class="sec-head"><h2 class="h-section">API map</h2><p>Every route needs a verified Firebase ID token. Role is enforced per route.</p></div>
      <div class="api">${[
      ["Shipments", [["GET", "/shipments", "list + filter"], ["GET", "/shipments/{id}/explainer", ""], ["POST", "/shipments/{id}/override", "dispatcher"]]],
      ["Vehicles & legs", [["GET", "/vehicles", ""], ["GET", "/legs/{leg_id}", "route-click panel"], ["GET", "/legs/{leg_id}/bounty-status", ""]]],
      ["Heatmap & hubs", [["GET", "/heatmap?hour={h}", "risk cells"], ["GET", "/hub-emergence/candidates", ""], ["POST", "/hub-emergence/candidates/{id}/approve", "admin"]]],
      ["Auctions & policy", [["GET", "/auctions/{id}", ""], ["POST", "/auctions/{id}/bid", "driver"], ["PUT", "/policy-mode", "admin"]]],
      ["Model registry", [["GET", "/model/status", ""], ["POST", "/model/reload", "admin"]]],
      ["Simulation & realtime", [["POST", "/simulate/tick", "prototype"], ["POST", "/simulate/inject-disruption", "prototype"], ["WS", "/ws/live", "tick stream"]]],
    ].map(([t, r]) => `<div class="card"><div class="card-h"><h2>${t}</h2></div><ul>${r.map(x => `<li><span class="meth">${x[0]}</span><code>${x[1]}</code><span>${x[2]}</span></li>`).join("")}</ul></div>`).join("")}</div></section>
  </div>${footHTML()}`;
  wireNav(root);
}

