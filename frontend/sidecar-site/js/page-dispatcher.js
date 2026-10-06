/* Dispatcher portal */
/* ---------- Dispatcher ---------- */
function dispatcher(root) {
  const audit = [];
  let selId = (SHIPMENTS.find(s => s.id === "S204") || SHIPMENTS.slice().sort((a, b) => b.T - a.T)[0] || {}).id;
  const who = () => (Session.account() || { name: "Dispatcher" }).name;
  let newCount = 0;
  const cur = () => SHIPMENTS.find(s => s.id === selId);
  const sorted = () => SHIPMENTS.slice().sort((a, b) => b.T - a.T);

  const body = `
  <div class="kpis" style="grid-template-columns:repeat(4,1fr)">
    <div class="kpi"><span class="k">In queue</span><div class="v num" id="kQ">0</div><span class="d">misplaced shipments</span></div>
    <div class="kpi"><span class="k">Hot zone</span><div class="v num" id="kH">0</div><span class="d dn">T ≥ 67, act first</span></div>
    <div class="kpi"><span class="k">Live auctions</span><div class="v num" id="kA">0</div><span class="d">reverse auctions open</span></div>
    <div class="kpi"><span class="k">Median re-plan</span><div class="v num">60<small> ms</small></div><span class="d">warm-start from graph memory</span></div>
  </div>
  <div class="grid g12">
    <section class="card s5"><div class="card-h"><h2>Misplaced shipment queue</h2><span class="pill"><span class="dot live"></span>sorted by temperature</span></div><div class="tbl-wrap" id="queue"></div></section>
    <section class="card s7"><div class="card-h"><h2>Recovery plan</h2><span id="planBadges"></span></div>
      <div class="two" style="align-items:start"><div id="planMap"></div><div id="planText"></div></div></section>
    <section class="card s7"><div class="card-h"><h2>Counterfactual explainer</h2><small>why this plan, and what lost</small></div><div id="explain"></div></section>
    <section class="card s5"><div class="card-h"><h2>Bounty auction</h2><small>Vickrey · second-price</small></div><div id="auction"></div></section>
    <section class="card s6"><div class="card-h"><h2>Override</h2><small>pick from the k-best plans</small></div><div id="override"></div></section>
    <section class="card s6"><div class="card-h"><h2>Foresight payoff</h2><small>time to a committed plan</small></div>${latencyBars(METRICS.latency)}<p class="explain-h">Audit trail</p><ul class="audit" id="audit"><li>No overrides yet. Every override and approval is logged here with its reason.</li></ul></section>
  </div>`;
  shell(root, "dispatcher", "Dispatcher console", "Recover misplaced shipments, hottest first.", `<span class="pill"><span class="dot live"></span>WebSocket live</span><button class="btn sm" id="injectD">Inject disruption</button>`, body);

  const map = createNetworkMap($("#planMap"), { heat: false, cands: false, legs: false, labels: false, hubs: false });

  function paintQueue() {
    $("#queue").innerHTML = `<table class="tbl"><thead><tr><th>Shipment</th><th>Zone</th><th>Temp</th><th class="nocase">λ ₹/hr</th></tr></thead><tbody>${sorted().map(s => {
      const z = zoneOf(s.T);
      return `<tr class="click ${s.id === selId ? "sel" : ""}" data-id="${s.id}" tabindex="0"><td><b>${s.id}</b>${s.isNew ? ' <span class="tag">new</span>' : ""}<br><small style="color:var(--ink-3)">${hub(s.at).name} → ${hub(s.to).name}</small></td><td><span class="zone ${z[1]}">${z[0]}</span></td><td><div class="tmeter"><div class="bar thin"><i style="width:${s.T}%;background:${s.T >= 67 ? "var(--hot)" : s.T >= 34 ? "var(--warm)" : "var(--cold)"}"></i></div><span class="num">${Math.round(s.T)}</span></div></td><td class="num">${Math.round(lambda(s)).toLocaleString("en-IN")}</td></tr>`;
    }).join("")}</tbody></table>`;
    $("#kQ").textContent = SHIPMENTS.length;
    $("#kH").textContent = SHIPMENTS.filter(s => s.T >= 67).length;
  }

  function emptyState() {
    $("#planBadges").innerHTML = "";
    $("#planText").innerHTML = `<div class="info-empty">${ic("route")}No misplaced shipments right now. Use <b>Inject disruption</b>: the recovery engine plans the shipment immediately.</div>`;
    $("#explain").innerHTML = `<div class="info-empty">${ic("alert")}The explainer appears when a shipment is selected.</div>`;
    $("#override").innerHTML = `<div class="info-empty">Nothing to override.</div>`;
    $("#auction").innerHTML = `<div class="info-empty">${ic("gavel")}No auction.</div>`;
    $("#kA").textContent = Bounty.openCount();
  }
  function paintPlan(full) {
    if (!cur()) return emptyState();
    const s = cur(), p = planFor(s), best = p.opts[0], z = zoneOf(s.T);
    $("#planBadges").innerHTML = `<span class="strat ${best.strat}">${best.strat.replace("_", "-")}</span>`;
    $("#planText").innerHTML = `<h3 class="leg-title">${s.id} · ${s.cargo}</h3>
      <p class="leg-sub">${hub(s.from).name} → <b>${hub(s.at).name}</b> (found here) → ${hub(s.to).name}</p>
      <div class="plan-cols" style="grid-template-columns:repeat(2,1fr)"><div><small>Temperature</small><b class="num">${Math.round(s.T)}</b> <span class="zone ${z[1]}" style="vertical-align:3px">${z[0]}</span></div><div><small>Urgency</small><b class="num">${inr(p.lam)}</b><span class="leg-sub">/hr</span></div><div><small>Plan cost</small><b class="num">${inr(best.c + best.hand)}</b></div><div><small>ETA</small><b class="num">${best.h.toFixed(1)} h</b></div></div>
      <p class="leg-sub"><b style="color:var(--ink)">${best.via}</b><br>Delivery to ${hub(s.to).name} status: ${p.live && !p.pending ? "Committed by the recovery engine (plan #" + best.planId + ")." : override.committed === s.id ? "Committed. Driver notified via bounty offer." : "awaiting approval"}.</p>
      <div class="actions" style="margin-top:12px"><button class="btn sm" id="approveBtn">Approve plan</button></div>`;
    if (full) map.setRoute([s.at, s.to], [{ hub: s.at, color: "var(--hot)", label: "Misplaced" }, { hub: s.to, color: "var(--good)", label: "Destination" }]);
    /* explainer: the backend E8 card when live (its reasons are the engine's own), sample maths otherwise */
    if (p.live) {
      const ex = p.explain, E = MAARG.esc;
      $("#explain").innerHTML = ex ? `<p class="explain-h" style="margin-top:4px">Chosen · ${E(ex.headline)}</p>
        <div class="alt win"><span class="strat ${E(ex.strategy)}">${E(ex.strategy.replace("_", "-"))}</span><div><b>${E(best.via)}</b><div class="why">${ex.why_chosen.map(E).join("<br>")}</div></div><span class="num"><b>${inr(ex.total_cost)}</b></span></div>
        <p class="explain-h">Rejected alternatives</p>${ex.alternatives.length ? ex.alternatives.map(a => `<div class="alt"><span class="strat ${E(a.strategy)}">${E(a.strategy.replace("_", "-"))}</span><div><div class="why">${E(a.reason)}</div></div><span class="num">${inr(a.total_cost)}</span></div>`).join("") : `<p class="leg-sub">No other feasible plan.</p>`}`
        : `<div class="info-empty">${ic("alert")}${E(p.opts[0].via)}</div>`;
      return;
    }
    const lam = p.lam;
    const rows = p.opts.slice(1).map(o => {
      const dh = o.h - best.h, dc = (o.c + o.hand) - (best.c + best.hand);
      const why = dh > 0 ? `Costs ${inr(Math.abs(dc))} ${dc >= 0 ? "more" : "less"} to move but arrives ${dh.toFixed(1)} h later. At λ = ${inr(lam)}/hr that delay adds ${inr(lam * dh)}.` : `Arrives ${(-dh).toFixed(1)} h sooner, but the ${inr(Math.abs(dc))} extra cost is more than the ${inr(lam * -dh)} of delay it saves.`;
      return `<div class="alt"><span class="strat ${o.strat}">${o.strat.replace("_", "-")}</span><div><b>${o.via}</b><div class="why">${why}</div></div><span class="num">${inr(o.w)}</span></div>`;
    }).join("");
    $("#explain").innerHTML = (s.cascade ? `<div class="cascade">${ic("alert").replace("<svg", '<svg width="22" height="22"')}<span>Cascade: temperature jumped <b class="num">${s.cascade[0]} → ${s.cascade[1]}</b> after an upstream delay, so λ rose from <b class="num">${inr(s.sla * (1 + s.cascade[0] / 50))}</b> to <b class="num">${inr(s.sla * (1 + s.cascade[1] / 50))}</b>/hr.</span></div>` : "") +
      `<p class="explain-h" style="margin-top:4px">Chosen · <span class="nocase">w(e) = C_transit + λ × transit_hours + handling</span></p>
      <div class="alt win"><span class="strat ${best.strat}">${best.strat.replace("_", "-")}</span><div><b>${best.via}</b><div class="why">${inr(best.c)} transit + ${inr(lam)}/hr × ${best.h.toFixed(1)} h + ${inr(best.hand)} handling. Lowest total weighted cost.</div></div><span class="num"><b>${inr(best.w)}</b></span></div>
      <p class="explain-h">Rejected alternatives</p>${rows}`;
  }

  /* override */
  const override = { committed: null };
  function paintOverride() {
    if (!cur()) return;
    const s = cur(), p = planFor(s);
    $("#override").innerHTML = `<div class="stack"><label class="field">Alternative plan<select id="ovSel">${p.opts.map((o, i) => `<option value="${i}">${i === 0 ? "★ Engine pick · " : ""}${o.strat.replace("_", "-")} · ${o.via} · ${inr(o.w)}</option>`).join("")}</select></label>
      <label class="field">Reason (required for an override)<textarea id="ovWhy" placeholder="e.g. Customer called; needs delivery before the 06:00 shift"></textarea></label>
      <div class="actions"><button class="btn sm" id="ovGo">Override plan</button></div></div>`;
    $("#ovGo").addEventListener("click", () => {
      const i = +$("#ovSel").value, why = $("#ovWhy").value.trim();
      if (i === 0) return toast("That is already the engine's pick. Choose another plan to override.");
      if (why.length < 6) return toast("Add a reason. Every override is written to the audit trail.");
      const o = p.opts[i];
      if (MAARG.live) {
        if (!o.planId) return toast("That option has no backend plan to commit.");
        MAARG.api(`/shipments/${s.dbId}/override`, { method: "POST", body: { chosen_plan_id: o.planId, reason: why } }).then(r => {
          logAudit(`<b>${MAARG.esc(who())}</b> overrode <b>${s.id}</b> to ${o.strat.replace("_", "-")} (${MAARG.esc(o.via)}). Reason: “${MAARG.esc(why)}” <small>· audit #${r.audit_log_id}</small>`);
          delete MAARG.state.plans[s.id]; MAARG.fetchPlan(s).then(() => { paintPlan(false); paintOverride(); });
          toast("Override committed on the backend and audit-logged (#" + r.audit_log_id + ")");
        }).catch(err => toast("Override failed: " + err.message));
        $("#ovWhy").value = ""; return;
      }
      logAudit(`<b>Rahul Nair</b> overrode <b>${s.id}</b> to ${o.strat.replace("_", "-")} (${o.via}). Reason: “${why}”`);
      override.committed = s.id; paintPlan(false); toast("Override committed and logged");
      $("#ovWhy").value = "";
    });
  }
  function logAudit(html) {
    const ul = $("#audit"); if (!audit.length) ul.innerHTML = ""; audit.unshift(html);
    ul.innerHTML = audit.map(a => `<li>${a}</li>`).join("");
  }

  /* auction: the shared bounty market, the same auctions the driver app and the Admin portal work with */
  let aSig = "";
  function paintAuction(force) {
    if (!cur()) return;
    const s = cur(), a = Bounty.forShip(s.id), host = $("#auction");
    $("#kA").textContent = Bounty.openCount();
    if (!a) { if (aSig === "none:" + s.id && !force) return; aSig = "none:" + s.id; host.innerHTML = `<div class="info-empty">${ic("gavel")}No auction for ${s.id} yet. Approving the plan opens one and sends the offer to every eligible driver.</div><div class="actions" style="margin-top:12px"><button class="btn sm" id="openA">Open auction now</button></div>`; return; }
    const sig = Bounty.view(a).sig; if (!force && sig === aSig) return; aSig = sig;
    host.innerHTML = `<p class="leg-sub" style="margin:0 0 10px"><b style="color:var(--ink)">${a.id}</b> for ${s.id} · pickup ${a.pickup}</p>` + BountyUI.monitor(a);
  }
  $("#auction").addEventListener("click", e => {
    if (e.target.id !== "openA") return;
    const a = Bounty.openFor(cur(), "dispatcher"); toast(`Auction ${a.id} opened. ${a.eligible.length} eligible vehicle${a.eligible.length === 1 ? "" : "s"}${a.eligible.includes(Bounty.MINE) ? ", including Truck 12 in the driver app" : ""}.`); paintAuction(true);
  });
  const off = Bounty.onChange(() => paintAuction(true));
  const at = setInterval(() => { Bounty.tick(); paintAuction(false); BountyUI.updateTimers($("#auction")); }, 1000);
  onLeave(() => { clearInterval(at); off(); });

  /* tick */
  const tk = setInterval(() => {
    if (!MAARG.live) SHIPMENTS.forEach(s => { s.T = clamp(0, 100, s.T + (Math.random() - .4) * 1.6); });
    paintQueue(); paintPlan(false);
  }, 2500);
  onLeave(() => clearInterval(tk));

  function select(id) { selId = id; paintQueue(); paintPlan(true); paintOverride(); paintAuction(true); }
  $("#queue").addEventListener("click", e => { const r = e.target.closest("tr[data-id]"); if (r) select(r.dataset.id); });
  $("#queue").addEventListener("keydown", e => { if (e.key === "Enter") { const r = e.target.closest("tr[data-id]"); if (r) select(r.dataset.id); } });
  $("#planText").addEventListener("click", e => {
    if (e.target.id !== "approveBtn") return;
    const s = cur(); if (!s) return;
    if (MAARG.live) {
      const p = planFor(s);
      if (p.pending) {
        toast("Running the recovery engine for " + s.id + "…");
        MAARG.api(`/simulate/recover/${s.dbId}`, { method: "POST", timeout: 30000 }).then(r => {
          logAudit(`Engine committed <b>${r.strategy}</b> for <b>${s.id}</b> at ${inr(r.total_cost)} (${Math.round(r.total_ms)} ms), approved by <b>${MAARG.esc(who())}</b>.`);
          delete MAARG.state.plans[s.id]; MAARG.fetchPlan(s).then(() => { paintPlan(true); paintOverride(); }); MAARG.refreshQueue();
          toast(`${r.shipment_code}: ${r.strategy} committed at ${inr(r.total_cost)} in ${Math.round(r.total_ms)} ms`);
        }).catch(err => toast("Recovery failed: " + err.message));
        return;
      }
      override.committed = s.id; logAudit(`<b>${MAARG.esc(who())}</b> approved the engine's plan for <b>${s.id}</b> (${p.opts[0].strat.replace("_", "-")}, ${inr(p.opts[0].w)}).`);
      paintPlan(false); const a = Bounty.openFor(s, "dispatcher");
      toast(`Plan approved. Offer ${a.id} mirrored to the driver app.`); paintAuction(true); return;
    }
    const b = planFor(s).opts[0];
    override.committed = s.id; logAudit(`<b>Rahul Nair</b> approved the engine's plan for <b>${s.id}</b> (${b.strat.replace("_", "-")}, ${inr(b.w)}).`);
    paintPlan(false); const a = Bounty.openFor(s, "dispatcher");
    toast(`Plan committed. Offer ${a.id} sent to ${a.eligible.length} eligible vehicle${a.eligible.length === 1 ? "" : "s"}${a.eligible.includes(Bounty.MINE) ? ", including Truck 12 in the driver app" : ""}.`); paintAuction(true);
  });
  $("#injectD").addEventListener("click", () => {
    if (MAARG.live) {
      toast("Injecting a disruption and running the recovery engine…");
      MAARG.api("/simulate/inject-disruption", { method: "POST", body: { type: "MISPLACE_SHIPMENT" } })
        .then(d => MAARG.api(`/simulate/recover/${d.target_id}`, { method: "POST", timeout: 30000 }).then(r => ({ d, r })))
        .then(async ({ d, r }) => {
          await MAARG.refreshQueue();
          const ns = SHIPMENTS.find(x => x.dbId === d.target_id); if (ns) { ns.isNew = true; select(ns.id); }
          logAudit(`Disruption: <b>${r.shipment_code}</b> misplaced; engine committed <b>${r.strategy}</b> at ${inr(r.total_cost)} in ${Math.round(r.total_ms)} ms.`);
          toast(`${r.shipment_code} misplaced → ${r.strategy} committed at ${inr(r.total_cost)} in ${Math.round(r.total_ms)} ms`);
        }).catch(err => toast("Inject failed: " + err.message));
      return;
    }
    newCount++;
    const ids = ["S520", "S521", "S522"], id = ids[(newCount - 1) % 3] + (newCount > 3 ? "x" + newCount : "");
    const from = HUBS[Math.floor(Math.random() * HUBS.length)], to = HUBS[(HUBS.indexOf(from) + 5) % HUBS.length];
    SHIPMENTS.push({ id, cargo: "Mixed parcels, 80 kg", from: from.id, at: HUBS[(HUBS.indexOf(from) + 2) % HUBS.length].id, to: to.id, sla: 90, T: 21, delay: .5, isNew: true });
    const ns = SHIPMENTS[SHIPMENTS.length - 1]; Bounty.openFor(ns, "dispatcher");
    toast("Disruption injected. " + id + " entered the queue in the Cold zone and an auction started.");
    select(id);
  });

  const onData = () => { if (!SHIPMENTS.some(s => s.id === selId)) selId = (sorted()[0] || {}).id; paintQueue(); paintPlan(false); paintOverride(); paintAuction(true); };
  const onPlan = e => { if (e.detail.id === selId) { paintPlan(true); paintOverride(); } };
  document.addEventListener("maarg:data", onData); document.addEventListener("maarg:plan", onPlan);
  onLeave(() => { document.removeEventListener("maarg:data", onData); document.removeEventListener("maarg:plan", onPlan); });

  paintQueue(); paintPlan(true); paintOverride(); paintAuction(true);
  document.addEventListener("themechange", () => map.redraw());
}

