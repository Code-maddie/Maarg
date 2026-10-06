/* Admin portal: Heat map · Metrics · Bounty · Hub emergence */

/* ---------- route info panel (admin is read-only here; dispatchers assign shipments) ---------- */
function legPanelHTML(l) {
  const [fa, fb] = [hub(l.from).name, hub(l.to).name];
  const pct = Math.round((1 - l.res / l.tot) * 100);
  const aboard = l.aboard.length ? l.aboard.map(a => { const z = zoneOf(a[1]); return `<div><span><b>${a[0]}</b> <span class="zone ${z[1]}">${z[0]}</span></span><span class="num">λ = ${inr(a[2] * (1 + a[1] / 50))}/hr</span></div>`; }).join("") : `<div><span style="color:var(--ink-3)">Nothing aboard yet</span></div>`;
  return `<p class="eyebrow">Leg ${l.id} · ${l.type}</p>
    <h3 class="leg-title" style="margin-top:4px">${l.veh} · ${fa} → ${fb}</h3>
    <p class="leg-sub">Departs ${l.dep} · Arrives ${l.arr}</p>
    <dl class="kv"><dt>Capacity</dt><dd><div class="cap-line"><div class="bar"><i style="width:${pct}%"></i></div><span class="num">${l.res} kg free</span></div><small style="color:var(--ink-3)">${l.tot} kg total</small></dd>
    <dt>Reliability</dt><dd class="num">${l.rel.toFixed(2)}</dd></dl>
    <p class="explain-h" style="margin-top:0">Aboard</p><div class="aboard">${aboard}</div>
    ${l.auction ? `<div class="auction-note"><span><b>Open auction</b> · closes in <b class="num" data-cd="${l.auction.closes}">${fmtCd(l.auction.closes)}</b></span><span>Best bid <b class="num">${inr(l.auction.best)}</b></span></div>` : `<p class="leg-sub">No auction on this leg.</p>`}`;
}

const AD = { mode: "BUSINESS", hour: 17, tab: "veh" };

/* ---------- views ---------- */
function viewHeat(el, reg) {
  if (MAARG.live && MAARG.state.policy && POLICIES[MAARG.state.policy]) AD.mode = MAARG.state.policy;
  el.innerHTML = pageHead("Heat map", "Live P(misplace) by hub and hour, with every route on the network.",
    `<span class="pill"><span class="dot live"></span>Engine online · tick <b class="num" id="tickN">${MAARG.live ? MAARG.state.tick : 4812}</b></span><button class="btn sm" id="injectBtn">Inject disruption</button>`) + `
  <div class="grid g12">
    <section class="card s8" aria-label="Network heat map">
      <div class="card-h"><h2>Risk across the network</h2><span class="pill">Click a route for details</span></div>
      <div id="adminMap"></div>
      <div class="map-tools">
        <label class="toggle"><input type="checkbox" id="heatOn" checked> Risk heat map</label>
        <label class="toggle"><input type="checkbox" id="candOn" checked> Hub candidates</label>
        <div class="slider-row"><label class="eyebrow" for="hourR">Time of day</label><input id="hourR" type="range" min="0" max="23" value="${AD.hour}"><span class="hour-badge num" id="hourV">${pad2(AD.hour)}:00</span></div>
      </div>
      <div class="map-legend"><span><i style="background:#E9D5A6"></i>low</span><span><i style="background:#D9A85B"></i>elevated</span><span><i style="background:#B8663A"></i>high</span><span><i style="background:#7B2D26"></i>critical</span><span><i style="background:var(--gold);border-radius:50% 50% 50% 0;transform:rotate(-45deg)"></i>proposed hub</span><span><i style="background:transparent;border:2px dashed var(--accent)"></i>leg with open auction</span></div>
    </section>
    <div class="s4" style="display:flex;flex-direction:column;gap:16px;min-width:0">
      <section class="card" id="legCard" aria-live="polite"><div class="card-h"><h2>Route info</h2></div><div class="info-empty">${ic("route")}Select a route on the map to see its vehicle, capacity and bounty status.</div></section>
      <section class="card"><div class="card-h"><h2>Policy mode</h2><small>re-weights T_base</small></div>
        <div class="seg" role="group" aria-label="Policy mode" id="polSeg">${Object.entries(POLICIES).map(([k, v]) => `<button type="button" data-m="${k}" class="${k === AD.mode ? "on" : ""}">${v.label}</button>`).join("")}</div>
        <div id="polBody"></div></section>
    </div>
  </div>`;
  const map = createNetworkMap($("#adminMap"), { hour: AD.hour, onLeg: l => { $("#legCard").innerHTML = `<div class="card-h"><h2>Route info</h2></div>` + legPanelHTML(l); } });
  const onHeat = e => { if (e.detail.hour === AD.hour) map.setHour(AD.hour); };
  document.addEventListener("maarg:heat", onHeat); reg(() => document.removeEventListener("maarg:heat", onHeat));
  $("#heatOn").addEventListener("change", e => map.setHeat(e.target.checked));
  $("#candOn").addEventListener("change", e => map.setCands(e.target.checked));
  $("#hourR").addEventListener("input", e => { AD.hour = +e.target.value; map.setHour(AD.hour); $("#hourV").textContent = pad2(AD.hour) + ":00"; });
  /* BUSINESS defaults from app/engines/e4_temperature/policy.py: other modes are shown as multiples of these */
  const BASE_W = { w_base: 20, w_time: 40, w_delay: 25, w_cascade: 15 };
  function previewHottest() {
    const host = $("#polRec"), s = SHIPMENTS.slice().sort((a, b) => b.T - a.T)[0];
    if (!host) return;
    if (!s) { host.innerHTML = `<div><span class="leg-sub">No misplaced shipment to re-plan. Inject one in the Dispatcher console.</span></div>`; return; }
    MAARG.api(`/simulate/route/${s.dbId}?k=3`).then(r => {
      const b = r.plans[0], E = MAARG.esc; if (!$("#polRec")) return;
      $("#polRec").innerHTML = b ? `<div><span class="strat ${E(b.strategy)}">${E(b.strategy.replace("_", "-"))}</span><span class="num"><b>${inr(b.total_cost)}</b> · T ${r.temperature.temperature.toFixed(1)} · λ ${inr(r.temperature.lam)}/hr</span></div>`
        : `<div><span class="leg-sub">No feasible plan for ${E(s.id)}.</span></div>`;
      $("#polNote").textContent = `${s.id} re-planned under ${r.temperature.policy_mode}: ${r.plans.length} feasible plan${r.plans.length === 1 ? "" : "s"} in ${r.compute_ms.toFixed(1)} ms.`;
    }).catch(err => { if ($("#polRec")) $("#polRec").innerHTML = `<div><span class="leg-sub">Preview failed: ${MAARG.esc(err.message)}</span></div>`; });
  }
  function paintPolicy() {
    if (MAARG.live) {
      const W = MAARG.state.weights || BASE_W;
      $("#polBody").innerHTML = `<div style="margin:16px 0 8px;display:grid;gap:8px">${["base", "time", "delay", "cascade"].map(k => { const v = (W["w_" + k] || 0) / BASE_W["w_" + k]; return `<div class="cap-line"><span style="width:64px;font-size:13px;color:var(--ink-2)">${k}</span><div class="bar thin"><i style="width:${Math.min(100, Math.round(v / 2 * 100))}%"></i></div><span class="num" style="width:46px;text-align:right;font-size:13px;white-space:nowrap">×${v.toFixed(1)}</span></div>`; }).join("")}</div>
        <p class="explain-h">Engine recommendation now (hottest misplaced shipment)</p><div class="aboard" id="polRec" style="margin-top:0"><div><span class="leg-sub">Re-planning…</span></div></div><p class="leg-sub" id="polNote"></p>`;
      previewHottest(); return;
    }
    const p = POLICIES[AD.mode], r = p.rec;
    $("#polBody").innerHTML = `<div style="margin:16px 0 8px;display:grid;gap:8px">${Object.entries(p.w).map(([k, v]) => `<div class="cap-line"><span style="width:64px;font-size:13px;color:var(--ink-2)">${k}</span><div class="bar thin"><i style="width:${Math.round(v / 2 * 100)}%"></i></div><span class="num" style="width:46px;text-align:right;font-size:13px;white-space:nowrap">×${v.toFixed(1)}</span></div>`).join("")}</div>
      <p class="explain-h">Recommended for S204 next tick</p><div class="aboard" style="margin-top:0"><div><span class="strat ${r.strat}">${r.strat.replace("_", "-")}</span><span class="num"><b>${inr(r.cost)}</b> · ETA ${r.eta}</span></div></div><p class="leg-sub"><b style="color:var(--ink)">${r.via}.</b> ${r.note}</p>`;
  }
  paintPolicy();
  $("#polSeg").addEventListener("click", e => {
    const b = e.target.closest("button[data-m]"); if (!b) return;
    if (MAARG.live) {
      MAARG.api("/policy-mode", { method: "PUT", body: { mode: b.dataset.m, reason: "Admin policy dial" } }).then(r => {
        AD.mode = r.mode; MAARG.state.policy = r.mode; MAARG.state.weights = r.weights;
        $$("#polSeg button").forEach(x => x.classList.toggle("on", x.dataset.m === r.mode)); paintPolicy();
        toast("Policy mode → " + POLICIES[r.mode].label + ". Saved on the backend and audit-logged; temperatures re-weighted.");
      }).catch(err => toast("Policy change failed: " + err.message));
      return;
    }
    AD.mode = b.dataset.m; $$("#polSeg button").forEach(x => x.classList.toggle("on", x === b)); paintPolicy();
    toast("Policy mode → " + POLICIES[AD.mode].label + ". Coefficients re-weighted; plans refresh next tick.");
  });
  let tickN = 4812;
  const clk = setInterval(() => { if (MAARG.live) tickN = MAARG.state.tick; else tickN++; const t = $("#tickN"); if (t) t.textContent = tickN; $$("[data-cd]").forEach(n => { const v = Math.max(0, +n.dataset.cd - 1); n.dataset.cd = v; n.textContent = fmtCd(v); }); }, 1000);
  reg(() => clearInterval(clk));
  $("#injectBtn").addEventListener("click", () => {
    if (MAARG.live) {
      const l = LEGS.find(x => x.aboard.length) || LEGS[0]; if (!l) return toast("No legs on the network.");
      const t0 = performance.now();
      MAARG.api("/simulate/inject-disruption", { method: "POST", body: { type: "DELAY_VEHICLE", target_id: l.vehicle_id, delay_hours: 2 } })
        .then(() => MAARG.api(`/simulate/cascade/vehicle/${l.vehicle_id}?max_depth=2`, { method: "POST", timeout: 30000 }))
        .then(c => {
          map.select(l.id); $("#legCard").innerHTML = `<div class="card-h"><h2>Route info</h2></div>` + legPanelHTML(l);
          toast(`${l.veh} delayed 2 h. Cascade updated ${c.shipments_updated} shipment${c.shipments_updated === 1 ? "" : "s"} (depth ${c.max_depth_reached}, ${c.terminated_by}) in ${Math.round(performance.now() - t0)} ms.`);
        }).catch(err => toast("Disruption failed: " + err.message));
      return;
    }
    toast("Truck 19 delayed 40 min. Warm-start re-plan finished in " + (52 + Math.round(Math.random() * 14)) + " ms.");
    map.select("L05"); $("#legCard").innerHTML = `<div class="card-h"><h2>Route info</h2></div>` + legPanelHTML(leg("L05"));
  });
  const th = () => map.redraw(); document.addEventListener("themechange", th); reg(() => document.removeEventListener("themechange", th));
}

function viewMetrics(el) {
  const M = METRICS;
  el.innerHTML = pageHead("Metrics dashboard", "How MAARG performs against a no-piggybacking baseline.", `<span class="pill">Sample simulation · 5,000 shipments · fixed seed</span>`) + `
  <div class="kpis">
    <div class="kpi feat"><div style="color:var(--btn-ink)">${ringSvg(.31, 78, 9)}</div><div><span class="k">Premium burn ratio</span><div class="v num">₹0.31<small> per ₹1 saved</small></div><span class="d">Foresight premium spent per rupee of dedicated cost avoided</span></div></div>
    <div class="kpi"><span class="k">On-time (SLA)</span><div class="v num">96.4<small>%</small></div><span class="d up">▲ 14.7 pts vs baseline 81.7%</span></div>
    <div class="kpi"><span class="k">Cost / shipment</span><div class="v num">₹412</div><span class="d up">▼ 30% vs baseline ₹587</span></div>
    <div class="kpi"><span class="k">Vehicle-km avoided</span><div class="v num">12,480</div><span class="d">via piggybacking</span></div>
    <div class="kpi"><span class="k">Median re-plan</span><div class="v num">60<small> ms</small></div><span class="d">warm-start from graph memory</span></div>
  </div>
  <div class="grid g12">
    <section class="card s6"><div class="card-h"><h2>On-time delivery vs baseline</h2><div class="legend-inline"><span><i style="background:var(--accent)"></i>MAARG</span><span><i style="background:var(--ink-3)"></i>Baseline</span></div></div>${lineChart(M.sla, M.slaBase)}</section>
    <section class="card s6"><div class="card-h"><h2>Cost per shipment</h2><small>₹, lower is better</small></div>${barsH([{ label: "MAARG", v: M.cost.sidecar, color: "var(--accent)" }, { label: "Baseline", v: M.cost.base, color: "var(--ink-3)" }], 640, v => inr(v))}
      <p class="leg-sub" style="margin-top:6px">How shipments were recovered:</p><div style="margin-top:10px">${mixBar(M.mix)}</div></section>
    <section class="card s12"><div class="card-h"><h2>Re-plan latency</h2><small>why Foresight and graph memory matter</small></div>${latencyBars(M.latency)}</section>
  </div>`;
}

function viewBounty(el, reg) {
  let sel = null, lastSig = "";
  const STATUS = a => { const v = Bounty.view(a); return !v.closed ? ["Open · " + fmtCd(v.left), "z-warm"] : !a.result ? ["Closing", "z-warm"] : a.result.winner == null ? ["Escalated", "z-hot"] : ["Won by " + a.result.winner, "z-cold"]; };
  el.innerHTML = pageHead("Bounty market", "Reverse auctions that pay vehicles already heading the right way. Driver, dispatcher and admin all see the same market.",
    `<span class="pill"><span class="dot live"></span><span id="bhOpen"></span></span><button class="btn sm ghost" id="bReset">Reset demo</button>`) + `
  <div class="kpis" style="grid-template-columns:repeat(5,1fr)" id="bKpis"></div>
  <div class="grid g12">
    <section class="card s5"><div class="card-h"><h2>Auctions</h2><small>select one to watch</small></div>
      <div class="open-row"><label class="field" style="flex:1;min-width:150px">Open an auction for a misplaced shipment<select id="openSel">${SHIPMENTS.map(s => `<option value="${s.id}">${s.id} · ${s.cargo} · ${hub(s.at).name} → ${hub(s.to).name}</option>`).join("")}</select></label><button class="btn sm" id="openBtn">Open</button></div>
      <div id="aList" style="margin-top:12px"></div>
      <p class="explain-h">How the bounty is set</p>
      <div class="formulas" style="grid-template-columns:1fr"><div><small>Ceiling</small><code>MaxBounty = min(λ × Δt_saved + customer premium, C_dedicated − C_overhead)</code></div><div><small>Payment (Vickrey)</small><code>Payment = min(second_lowest_bid, MaxBounty)</code></div></div>
      <p class="leg-sub" style="margin-top:10px">A declined or timed-out offer moves to the next vehicle in the escalation ladder. A customer's expedite amount raises the ceiling as an input, never as an override.</p></section>
    <section class="card s7"><div class="card-h"><h2 id="aTitle">Auction monitor</h2><small>Vickrey · second-price</small></div><div id="aMon"></div></section>
    <section class="card s6"><div class="card-h"><h2>Activity</h2><small>live from the driver and dispatcher apps</small></div><ul class="feed" id="bFeed"></ul></section>
    <section class="card s6"><div class="card-h"><h2>Settled (last 24 h)</h2><small>bounty paid vs cost of a dedicated vehicle</small></div><div class="tbl-wrap" id="bLedger"></div></section>
  </div>`;
  const auctions = () => Bounty.get().auctions;
  const controls = (a, v) => v.closed ? "" : `<div class="actions" style="margin-top:14px"><button class="btn sm ghost" data-act="ext" data-id="${a.id}">Extend +2 min</button><button class="btn sm ghost" data-act="close" data-id="${a.id}">Close now</button></div>`;
  function paintKpis() {
    const d = Bounty.get(), day = Date.now() - 864e5, L = d.ledger.filter(l => l.at > day), paid = L.filter(l => l.status === "paid"), pend = L.filter(l => l.status === "pending");
    const sum = (x, k) => x.reduce((t, l) => t + l[k], 0), open = auctions().filter(a => !Bounty.view(a).closed).length;
    $("#bhOpen").textContent = open + " auction" + (open === 1 ? "" : "s") + " open";
    $("#bKpis").innerHTML = `<div class="kpi"><span class="k">Open auctions</span><div class="v num">${open}</div><span class="d">vehicles bidding now</span></div>
      <div class="kpi"><span class="k">Bounty paid, 24 h</span><div class="v num">${inr(sum(paid, "paid"))}</div><span class="d">${paid.length} settled</span></div>
      <div class="kpi"><span class="k">Pending payouts</span><div class="v num">${inr(sum(pend, "paid"))}</div><span class="d">${pend.length ? "released when the driver delivers" : "nothing pending"}</span></div>
      <div class="kpi"><span class="k">Average bounty</span><div class="v num">${inr(paid.length ? sum(paid, "paid") / paid.length : 0)}</div><span class="d">second-lowest bid, capped</span></div>
      <div class="kpi"><span class="k">Saved vs dedicated</span><div class="v num">${L.length ? Math.round((1 - sum(L, "paid") / sum(L, "ded")) * 100) : 0}<small>%</small></div><span class="d up">${inr(sum(L, "ded") - sum(L, "paid"))} not spent on new trucks</span></div>`;
  }
  function paintList() {
    $("#aList").innerHTML = auctions().slice(0, 9).map(a => { const st = STATUS(a), drv = a.eligible.includes(Bounty.MINE); return `<button type="button" class="alist-item ${a.id === sel ? "on" : ""}" data-id="${a.id}"><span><b>${a.id}</b> · ${a.ship}${drv ? ' <span class="tag">driver app</span>' : ""}<br><small style="color:var(--ink-3)">${a.atName} → ${a.toName} · ${a.cargo}</small></span><span class="zone ${st[1]}" data-st="${a.id}">${st[0]}</span></button>`; }).join("");
  }
  function paintMon() {
    const a = auctions().find(x => x.id === sel); if (!a) { $("#aMon").innerHTML = `<div class="info-empty">${ic("gavel")}No auction selected.</div>`; return; }
    $("#aTitle").textContent = `${a.id} · ${a.ship} · ${a.atName} → ${a.toName}`;
    $("#aMon").innerHTML = BountyUI.monitor(a, { controls });
  }
  function paintFeed() {
    $("#bFeed").innerHTML = Bounty.get().events.slice(0, 8).map(e => `<li>${e.msg}<small>${BountyUI.ago(e.t)} · ${e.d ? "driver app" : "market"}</small></li>`).join("");
  }
  function paintLedger() {
    const L = Bounty.get().ledger.filter(l => l.at > Date.now() - 864e5);
    $("#bLedger").innerHTML = `<table class="tbl"><thead><tr><th>Auction</th><th>Winner</th><th>Paid</th><th>Dedicated</th><th>Status</th></tr></thead><tbody>${L.map(l => `<tr><td><b>${l.id}</b> · ${l.ship}</td><td>${l.winner}${l.by === "driver" ? ' <span class="tag">driver app</span>' : ""}</td><td class="num">${inr(l.paid)}</td><td class="num">${inr(l.ded)}</td><td>${l.status === "paid" ? '<span class="up">Paid</span>' : '<span style="color:var(--warm)" title="Released when the driver delivers">Pending</span>'}</td></tr>`).join("")}</tbody></table>`;
  }
  const sigOf = () => { const a = auctions().find(x => x.id === sel); return Bounty.rev() + "|" + (a ? Bounty.view(a).sig : "") + "|" + auctions().map(x => Bounty.view(x).closed ? 1 : 0).join(""); };
  function paintAll() { paintKpis(); paintList(); paintMon(); paintFeed(); paintLedger(); lastSig = sigOf(); }
  sel = (auctions().find(a => a.eligible.includes(Bounty.MINE) && !Bounty.view(a).closed) || auctions()[0] || {}).id;
  paintAll();

  el.addEventListener("click", e => {
    const li = e.target.closest(".alist-item"); if (li) { sel = li.dataset.id; paintList(); paintMon(); return; }
    const b = e.target.closest("[data-act]");
    if (b) { const id = b.dataset.id; if (b.dataset.act === "ext") { Bounty.extend(id, 120); toast("Extended " + id + " by 2 minutes"); } else { Bounty.closeNow(id); toast(id + " closed early"); } return; }
    if (e.target.id === "openBtn") { const s = SHIPMENTS.find(x => x.id === $("#openSel").value), a = Bounty.openFor(s, "admin"); sel = a.id; toast(`Auction ${a.id} open for ${s.id}` + (a.eligible.includes(Bounty.MINE) ? ". Truck 12 has the offer in the driver app." : "")); }
    if (e.target.id === "bReset") { Bounty.reset(); sel = auctions()[0].id; toast("Bounty market reset to the demo data"); }
  });
  const off = Bounty.onChange(() => { if (!el.isConnected) return; if (!auctions().some(x => x.id === sel)) sel = (auctions()[0] || {}).id; paintAll(); });
  const iv = setInterval(() => {
    if (!el.isConnected) return clearInterval(iv);
    Bounty.tick(); const s = sigOf(); if (s !== lastSig) { paintAll(); return; }
    BountyUI.updateTimers(el);
    $$("[data-st]", el).forEach(z => { const a = auctions().find(x => x.id === z.dataset.st); if (a) { const st = STATUS(a); if (z.textContent !== st[0]) z.textContent = st[0]; } });
    paintFeed();
  }, 1000);
  reg(() => { clearInterval(iv); off(); });
}

function viewHubs(el, reg) {
  el.innerHTML = pageHead("Hub emergence", "Where heavy usage meets high risk, MAARG proposes a new hub for you to approve.", `<span class="pill">HubScore = usage (30d) × mean risk</span>`) + `
  <div class="grid g12">
    <section class="card s7"><div class="card-h"><h2>Candidates on the map</h2><div class="legend-inline"><span><i style="background:var(--gold);height:10px;width:10px;border-radius:50%"></i>proposed hub</span></div></div>
      <div id="hubMap"></div>
      <div class="map-tools"><div class="slider-row"><label class="eyebrow" for="hubHour">Time of day</label><input id="hubHour" type="range" min="0" max="23" value="${AD.hour}"><span class="hour-badge num" id="hubHourV">${pad2(AD.hour)}:00</span></div></div>
      <p class="leg-sub" style="margin-top:10px">A gold pin on a hot cell is the reason a hub is proposed there.</p></section>
    <section class="card s5"><div class="card-h"><h2>Candidate hubs</h2><small>ranked by hub score</small></div><div id="candList"></div></section>
    <section class="card s12"><div class="card-h"><h2>Network records</h2><input class="search" id="tblQ" type="search" placeholder="Filter…" aria-label="Filter records"></div>
      <div class="tabs" role="tablist"><button class="on" data-t="veh" role="tab">Vehicles</button><button data-t="hub" role="tab">Hubs</button><button data-t="usr" role="tab">Users</button><button class="btn sm soft" style="margin-left:auto" id="addBtn">+ Add</button></div>
      <div class="tbl-wrap" id="tblHost"></div></section>
  </div>`;
  const map = createNetworkMap($("#hubMap"), { hour: AD.hour, legs: false });
  $("#hubHour").addEventListener("input", e => { AD.hour = +e.target.value; map.setHour(AD.hour); $("#hubHourV").textContent = pad2(AD.hour) + ":00"; paintTbl(); });
  const onHeatH = e => { if (e.detail.hour === AD.hour) { map.setHour(AD.hour); paintTbl(); } };
  document.addEventListener("maarg:heat", onHeatH); reg(() => document.removeEventListener("maarg:heat", onHeatH));
  function paintCands() {
    if (!CANDIDATES.length) { $("#candList").innerHTML = `<div class="info-empty">${ic("hub")}No corridor is both busy and risky enough yet. Candidates appear as scored traffic builds up.</div>`; return; }
    $("#candList").innerHTML = CANDIDATES.slice().sort((a, b) => b.score - a.score).map(c => `<div class="cand"><h3><span class="gold-dot"></span>${c.name}</h3>
      <div class="m"><span>Uses (30d) <b class="num">${c.usage}</b></span><span>Mean risk <b class="num">${c.risk.toFixed(2)}</b></span><span>Score <b class="num">${c.score}</b></span><span>Saves <b class="num">₹${c.save} L/yr</b></span></div>
      <div class="a">${c.status === "PENDING" ? `<button class="btn sm" data-a="ok" data-id="${c.id}">Approve</button><button class="btn sm ghost" data-a="no" data-id="${c.id}">Reject</button>` : c.status === "APPROVED" ? `<span class="status-approved">✓ Approved</span>` : `<span class="status-rejected">Rejected</span>`}</div></div>`).join("");
  }
  paintCands();
  $("#candList").addEventListener("click", e => {
    const b = e.target.closest("button[data-a]"); if (!b) return;
    const c = CANDIDATES.find(x => x.id === b.dataset.id);
    if (MAARG.live && c.candidate_id) {
      const ok = b.dataset.a === "ok";
      MAARG.api(`/hub-emergence/candidates/${c.candidate_id}/${ok ? "approve" : "reject"}`, { method: "POST", body: { reason: (ok ? "Approved" : "Rejected") + " from the admin portal" } })
        .then(r => { c.status = ok ? "APPROVED" : "REJECTED"; paintCands(); map.redraw(); toast(ok ? `${c.name} approved: hub ${r.code} created (audit-logged)` : `${c.name} rejected (audit-logged)`); })
        .catch(err => toast("Hub decision failed: " + err.message));
      return;
    }
    c.status = b.dataset.a === "ok" ? "APPROVED" : "REJECTED"; paintCands(); map.redraw();
    toast(c.status === "APPROVED" ? c.name + " approved and added to the hub table (audit-logged)" : c.name + " rejected (audit-logged)");
  });
  function paintTbl() {
    const q = ($("#tblQ").value || "").toLowerCase();
    let head, rows;
    if (AD.tab === "veh") {
      head = ["Vehicle", "Type", "Route", "Free capacity", "Reliability"];
      rows = VEHICLES.filter(v => (v.id + v.route + v.type).toLowerCase().includes(q)).map(v => [`<b>${v.id}</b>`, v.type, v.route, `<div class="cap-line"><div class="bar thin"><i style="width:${Math.round(v.res / v.tot * 100)}%"></i></div><span class="num">${v.res}/${v.tot} kg</span></div>`, `<span class="num">${v.rel.toFixed(2)}</span>`]);
    } else if (AD.tab === "hub") {
      head = ["Hub", "Code", "Risk now", "Legs touching"];
      rows = HUBS.filter(h => (h.name + h.id).toLowerCase().includes(q)).map(h => { const r = riskAt(h, AD.hour); return [`<b>${h.name}</b>`, h.id, `<div class="cap-line"><div class="bar thin"><i style="width:${Math.round(r * 100)}%;background:${r > .6 ? "var(--hot)" : r > .35 ? "var(--warm)" : "var(--good)"}"></i></div><span class="num">${r.toFixed(2)}</span></div>`, `<span class="num">${LEGS.filter(l => l.from === h.id || l.to === h.id).length}</span>`]; });
    } else {
      head = ["Name", "Email", "Role", "Last seen"];
      rows = USERS.filter(u => (u.name + u.email + u.role).toLowerCase().includes(q)).map(u => [`<b>${u.name}</b>`, u.email, `<span class="chip">${u.role}</span>`, u.seen]);
    }
    $("#tblHost").innerHTML = `<table class="tbl"><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="5" style="color:var(--ink-3)">No matches.</td></tr>`}</tbody></table>`;
  }
  paintTbl();
  $("#tblQ").addEventListener("input", paintTbl);
  $$(".tabs [data-t]").forEach(b => b.addEventListener("click", () => { AD.tab = b.dataset.t; $$(".tabs [data-t]").forEach(x => x.classList.toggle("on", x === b)); paintTbl(); }));
  $("#addBtn").addEventListener("click", () => toast("New " + ({ veh: "vehicle", hub: "hub", usr: "user" })[AD.tab] + " form is coming in the full build"));
  const th = () => map.redraw(); document.addEventListener("themechange", th); reg(() => document.removeEventListener("themechange", th));
}

function admin(root) {
  const VIEWS = [["heat", "Heat map", "heat"], ["metrics", "Metrics", "chart"], ["bounty", "Bounty", "gavel"], ["hubs", "Hub emergence", "hub"]];
  const fns = { heat: viewHeat, metrics: viewMetrics, bounty: viewBounty, hubs: viewHubs };
  let cleanups = [], active = VIEWS.find(v => v[0] === location.hash.slice(1)) ? location.hash.slice(1) : "heat";
  shell(root, "admin", "", "", "", `<div id="view"></div>`, { views: VIEWS, active, noHead: true });
  function go(v) {
    cleanups.forEach(f => { try { f(); } catch (e) { } }); cleanups = []; active = v;
    $$("[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === v));
    $("#view").innerHTML = ""; fns[v]($("#view"), f => cleanups.push(f));
    history.replaceState(null, "", "#" + v); window.scrollTo(0, 0);
  }
  $$("[data-view]").forEach(b => b.addEventListener("click", () => go(b.dataset.view)));
  go(active);
}
