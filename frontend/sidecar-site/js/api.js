/* MAARG live data layer.
   Connects the portals to the FastAPI backend WITHOUT rewriting them:

   - Hydration refills the arrays data.js already exposes (HUBS, LEGS, CANDIDATES, SHIPMENTS,
     VEHICLES) in place, so every existing page renders live data through its existing code.
   - planFor(), heatPoints() and riskAt() keep their signatures but are backed by the real engines
     (E6/E7 k-best plans, E8 explanations, E1 risk by hour).
   - Atomic: everything is fetched first and applied only if every request succeeded. A page is
     either fully live or fully sample, never a mix (sample and live hub codes differ).
   - Graceful: if the backend is unreachable the page keeps its sample data and says so.
   - Auth: sends the Firebase ID token when sign-in produced one. The browser gets the Firebase web
     config from GET /auth/web-config, so this static site needs no build step and no embedded keys.

   The backend origin comes from window.MAARG_CONFIG.API_BASE_URL, written at build time by
   frontend/scripts/generate-config.js. */
const MAARG = (() => {
  const cfg = window.MAARG_CONFIG || {};
  const BASE = String(cfg.API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");
  const TOKEN_KEY = "maarg-id-token";
  const HYDRATE_TIMEOUT = 9000;
  const LIVE_ROLES = { admin: 1, dispatcher: 1, customer: 1 };   // driver stays on the offer simulator

  const state = {
    live: false, role: null, reason: "", tick: 0, now: null, world: null,
    heat: {}, hubRisk: {}, plans: {}, inflight: {}, policy: null, weights: null,
    auth: { mode: null, token: false },
  };

  /* ---------- HTTP ---------- */
  const token = () => { try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return null; } };
  async function api(path, { method = "GET", body, timeout = 8000 } = {}) {
    const ctrl = new AbortController(), to = setTimeout(() => ctrl.abort(), timeout);
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const t = token(); if (t) headers.Authorization = "Bearer " + t;
    try {
      const r = await fetch(BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: ctrl.signal });
      const text = await r.text(); let data = null; try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
      if (!r.ok) { const err = new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : r.statusText); err.status = r.status; throw err; }
      return data;
    } finally { clearTimeout(to); }
  }

  /* ---------- Firebase sign-in (existing project, existing accounts) ---------- */
  async function signIn(email, password) {
    try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { }
    try {
      const wc = await api("/auth/web-config", { timeout: 3000 });
      state.auth.mode = wc.auth_mode;
      if (!wc.configured) return { ok: false, reason: "Firebase web config not found" };
      const ctrl = new AbortController(), to = setTimeout(() => ctrl.abort(), 6000);
      const r = await fetch("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + encodeURIComponent(wc.firebase.apiKey), {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: ctrl.signal,
        body: JSON.stringify({ email, password, returnSecureToken: true }),
      }).finally(() => clearTimeout(to));
      const j = await r.json();
      if (!r.ok) return { ok: false, reason: (j.error && j.error.message) || "sign-in failed" };
      try { sessionStorage.setItem(TOKEN_KEY, j.idToken); } catch (e) { }
      return { ok: true };
    } catch (e) { return { ok: false, reason: e.name === "AbortError" ? "timeout" : String(e.message || e) }; }
  }
  function signOut() { try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { } }

  /* ---------- mapping backend -> data.js shapes ---------- */
  const refill = (arr, items) => { arr.length = 0; items.forEach(x => arr.push(x)); };
  function toShipment(it) {
    const T = it.temperature || 0, now = state.now ? state.now.getTime() : Date.now();
    const overdue = it.deadline_at ? Math.max(0, (now - new Date(it.deadline_at).getTime()) / 36e5) : 0;
    return {
      id: it.code, dbId: it.id, live: true, status: it.status,
      cargo: `${it.status === "RECOVERING" ? "Recovering" : it.status === "MISPLACED" ? "Misplaced" : "In transit"}, ${Math.round(it.weight_kg)} kg`,
      from: it.origin_hub, at: it.current_hub || it.origin_hub, to: it.dest_hub,
      sla: it.lam / (1 + T / 50),            // exact inverse of data.js lambda(), so lambda(s) === backend λ
      T, delay: Math.round(overdue * 10) / 10, pressure: it.pressure, emergency: it.emergency, p: it.p_misplace,
      deadline: it.deadline_at,
    };
  }
  const via = plan => {
    const hops = plan.path || [];
    if (!hops.length) return plan.strategy === "DEDICATED" ? "Dedicated vehicle" : "Route pending";
    const chain = [hops[0].from_hub].concat(hops.map(h => h.to_hub)).map(c => (hub(c) || { name: c }).name).join(" → ");
    const legs = hops.filter(h => h.leg_id != null).map(h => "leg " + h.leg_id);
    return (plan.strategy === "DEDICATED" || !legs.length ? "Dedicated vehicle · " : legs.join(" + ") + " · ") + chain;
  };
  const toOpt = pl => ({ strat: pl.strategy, via: via(pl), c: pl.total_cost, h: pl.transit_hours || 0, hand: 0, w: pl.total_cost, planId: pl.id, status: pl.status, reason: pl.rejection_reason, live: true });

  /* ---------- engine-backed adapters (same signatures as data.js) ---------- */
  const _planFor = window.planFor, _heatPoints = window.heatPoints, _riskAt = window.riskAt;

  function placeholderPlan(s, msg) {
    return { lam: lambda(s), base: 0, live: true, pending: true, explain: null,
      opts: [{ strat: "PENDING", via: msg || "Loading the plan from the recovery engine…", c: 0, h: 0, hand: 0, w: 0, live: true, pending: true }] };
  }
  async function fetchPlan(s) {
    if (state.inflight[s.id]) return state.inflight[s.id];
    state.inflight[s.id] = (async () => {
      const bundle = await api(`/shipments/${s.dbId}/recovery-plan`);
      let explain = null;
      if (bundle.committed) { try { explain = await api(`/shipments/${s.dbId}/explainer`); } catch (e) { explain = null; } }
      const opts = [bundle.committed].concat(bundle.alternatives || []).filter(Boolean).map(toOpt);
      state.plans[s.id] = opts.length
        ? { lam: lambda(s), base: 0, live: true, opts, explain, rejected: (bundle.rejected || []).map(toOpt) }
        : placeholderPlan(s, "No recovery plan yet. Approve runs the full recovery engine.");
      if (!opts.length) state.plans[s.id].unplanned = true;
      emit("maarg:plan", { id: s.id });
      return state.plans[s.id];
    })().finally(() => { delete state.inflight[s.id]; });
    return state.inflight[s.id];
  }
  function livePlanFor(s) {
    if (!s || !s.live) return _planFor(s);
    const p = state.plans[s.id];
    if (p) return p;
    fetchPlan(s).catch(() => { state.plans[s.id] = placeholderPlan(s, "Plan unavailable (backend error)."); });
    return placeholderPlan(s);
  }
  async function fetchHeat(hour) {
    if (state.heat[hour] || state.inflight["h" + hour]) return;
    state.inflight["h" + hour] = api(`/map/heat?hour=${hour}`).then(h => {
      state.heat[hour] = h.points; state.hubRisk[hour] = h.hub_risk; state.heatSource = h.source;
      emit("maarg:heat", { hour });
    }).catch(() => { }).finally(() => { delete state.inflight["h" + hour]; });
  }
  function nearestHour(hour) { const ks = Object.keys(state.heat).map(Number); return ks.length ? ks.sort((a, b) => Math.abs(a - hour) - Math.abs(b - hour))[0] : null; }
  function liveHeatPoints(hour) {
    if (!state.live) return _heatPoints(hour);
    if (state.heat[hour]) return state.heat[hour];
    fetchHeat(hour); const n = nearestHour(hour); return n == null ? [] : state.heat[n];
  }
  function liveRiskAt(h, hour) {
    if (!state.live) return _riskAt(h, hour);
    const table = state.hubRisk[hour] || state.hubRisk[nearestHour(hour)] || {};
    return clamp(0, 1, table[h.id] != null ? table[h.id] : h.base || 0);
  }

  /* ---------- hydration ---------- */
  async function loadQueue() {
    const q = await api("/shipments?status=MISPLACED,RECOVERING&limit=60");
    return q.items.map(toShipment);
  }
  async function hydrate(role) {
    const st = await api("/simulate/state");
    if (!st.hubs) throw Object.assign(new Error("Backend is running but has no simulated world yet (POST /simulate/reset)."), { soft: true });
    // Admin sees E3's current output: regenerate candidates from scored traffic (idempotent).
    if (role === "admin") await api("/hub-emergence/candidates?regenerate=true");
    const [net, pol] = await Promise.all([api("/map/network?leg_limit=40"), api("/policy-mode")]);
    let queue = [], tracked = null;
    if (role === "dispatcher" || role === "admin") queue = await loadQueue();
    if (role === "customer") {
      queue = await loadQueue();
      tracked = queue.slice().sort((a, b) => (b.status === "RECOVERING") - (a.status === "RECOVERING") || b.T - a.T)[0] || null;
      if (!tracked) { const t = await api("/shipments?status=IN_TRANSIT&limit=1"); tracked = t.items.length ? toShipment(t.items[0]) : null; }
      queue = tracked ? [tracked] : [];
    }

    /* ---- every request succeeded: apply atomically ---- */
    state.now = new Date(st.now); state.tick = st.tick; state.world = st;
    state.policy = pol.mode; state.weights = pol.weights;
    refill(HUBS, net.hubs); refill(LEGS, net.legs); refill(CANDIDATES, net.candidates);
    state.heat[net.hour] = net.heat.points; state.hubRisk[net.hour] = net.heat.hub_risk; state.heatSource = net.heat.source;
    refill(VEHICLES, LEGS.slice(0, 40).map(l => ({ id: l.veh, type: l.type, route: hub(l.from).name + " → " + hub(l.to).name, tot: l.tot, res: l.res, rel: l.rel })));
    refill(SHIPMENTS, queue);
    if (role === "customer" && tracked && typeof ROUTE_WP !== "undefined") {
      const wp = [tracked.from, tracked.at, tracked.to].filter((c, i, a) => c && a.indexOf(c) === i).map(c => hub(c)).filter(Boolean);
      if (wp.length >= 2) refill(ROUTE_WP, wp.map(h => [h.name, h.lat, h.lon]));
    }
    window.planFor = livePlanFor; window.heatPoints = liveHeatPoints; window.riskAt = liveRiskAt;
    state.live = true; state.tracked = tracked ? tracked.id : null;

    // Warm the plan cache and the other 23 heat hours without blocking first paint.
    SHIPMENTS.forEach(s => fetchPlan(s).catch(() => { }));
    if (role === "admin") setTimeout(() => { let h = 0; const next = () => { if (h > 23) return; fetchHeat(h++); setTimeout(next, 120); }; next(); }, 800);
  }
  async function refreshQueue() {
    if (!state.live || !(state.role in LIVE_ROLES) || state.role === "customer") return;
    try {
      const queue = await loadQueue(), before = {};
      SHIPMENTS.forEach(s => { before[s.id] = s.status + ":" + Math.round(s.T); });
      refill(SHIPMENTS, queue);
      queue.forEach(s => { if (before[s.id] !== s.status + ":" + Math.round(s.T)) { delete state.plans[s.id]; fetchPlan(s).catch(() => { }); } });
      emit("maarg:data", {});
    } catch (e) { }
  }

  /* ---------- realtime ---------- */
  let ws = null, wsDelay = 1000, refreshTimer = null;
  function connectWS() {
    if (!state.live) return;
    const url = BASE.replace(/^http/, "ws") + "/ws/live" + (token() ? "?token=" + encodeURIComponent(token()) : "");
    try { ws = new WebSocket(url); } catch (e) { return; }
    ws.onopen = () => { wsDelay = 1000; state.ws = true; badge(); };
    ws.onmessage = m => {
      let e; try { e = JSON.parse(m.data); } catch (x) { return; }
      if (e.type === "tick") { state.tick = e.payload.tick; state.now = new Date(e.payload.now); emit("maarg:tick", e.payload); badge(); }
      if (e.type === "policy_changed") { state.policy = e.payload.mode; state.weights = e.payload.weights; emit("maarg:policy", e.payload); }
      if (e.type === "plan_changed") {
        /* A plan can change without its temperature changing (override, re-plan from another tab):
           drop the cached plan for that shipment so the next paint shows the committed one. */
        const s = SHIPMENTS.find(x => x.dbId === e.payload.shipment_id);
        if (s) { delete state.plans[s.id]; fetchPlan(s).catch(() => { }); }
      }
      if (["tick", "plan_changed", "disruption", "cascade_event"].includes(e.type)) { clearTimeout(refreshTimer); refreshTimer = setTimeout(refreshQueue, 350); }
    };
    ws.onclose = () => { state.ws = false; badge(); setTimeout(connectWS, wsDelay); wsDelay = Math.min(15000, wsDelay * 2); };
  }

  /* ---------- UI helpers ---------- */
  function emit(name, detail) { document.dispatchEvent(new CustomEvent(name, { detail })); }
  function badge() {
    let b = document.getElementById("maargSource");
    if (!b) { b = document.createElement("div"); b.id = "maargSource"; b.setAttribute("role", "status");
      b.style.cssText = "display:none;position:fixed;right:14px;bottom:14px;z-index:9999;padding:7px 12px;border-radius:999px;font:600 12px/1.2 system-ui,sans-serif;box-shadow:0 2px 10px rgba(0,0,0,.18);max-width:min(92vw,420px)";
      document.body.appendChild(b); }
    if (state.live) { b.dataset.source = "live"; b.style.background = "#1f5132"; b.style.color = "#fff";
      b.textContent = `● Live backend · tick ${state.tick}${state.ws ? "" : " · reconnecting"}${state.auth.token ? " · signed in" : ""}`; }
    else if (state.role === "driver") { b.dataset.source = "simulated"; b.style.background = "#5a4a2c"; b.style.color = "#fff";
      b.textContent = "Driver offers are simulated in the browser (live auction window: Phase 23)"; }
    else { b.dataset.source = "sample"; b.style.background = "#7b2d26"; b.style.color = "#fff";
      b.textContent = "Sample data · " + (state.reason || "backend offline"); }
    b.title = state.live ? "Data from " + BASE : state.reason;
  }

  /* ---------- public ---------- */
  const esc = v => String(v == null ? "" : v).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  return {
    state, api, esc, signIn, signOut, refreshQueue, fetchPlan, BASE,
    get live() { return state.live; },
    trackedId: () => state.tracked || "S204",
    boot(role, start) {
      state.role = role; state.auth.token = !!token();
      const done = () => { if (document.body) badge(); try { start(); } catch (e) { console.error("MAARG page failed to start", e); } if (state.live) connectWS(); };
      if (!(role in LIVE_ROLES)) { state.reason = "simulated"; done(); return; }
      let settled = false;
      const timer = setTimeout(() => { if (settled) return; settled = true; state.reason = "backend did not answer in time"; done(); }, HYDRATE_TIMEOUT);
      hydrate(role).then(() => { state.reason = ""; })
        .catch(e => { state.live = false; state.reason = e.status === 401 ? "not signed in to the backend (401)" : e.soft ? e.message : "backend offline"; console.info("MAARG: using sample data:", e.message || e); })
        .finally(() => { if (settled) return; settled = true; clearTimeout(timer); done(); });
    },
  };
})();
