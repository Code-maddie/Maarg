/* Driver portal (doc §4.3 and §5.3): My route · Offer inbox · Active pickup · Earnings.
   Offers, bids, results and payouts all come from the shared Bounty market, so the Admin and Dispatcher portals see every action live. */
function fakeQR(seed) {
  let h = 2166136261; for (const c of seed) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); }
  const rnd = () => { h ^= h << 13; h ^= h >>> 17; h ^= h << 5; return ((h >>> 0) % 1000) / 1000; };
  const N = 21, cells = [];
  const finder = (x, y) => (x < 7 && y < 7) || (x > 13 && y < 7) || (x < 7 && y > 13);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    let on;
    if (finder(x, y)) { const fx = x % 14 > 6 ? x - 14 : x, fy = y > 13 ? y - 14 : y; on = (fx === 0 || fx === 6 || fy === 0 || fy === 6) || (fx >= 2 && fx <= 4 && fy >= 2 && fy <= 4); }
    else on = rnd() > .52;
    if (on) cells.push(`<rect x="${x}" y="${y}" width="1" height="1"/>`);
  }
  return `<svg class="qr" viewBox="-1 -1 23 23" fill="#2B2118" role="img" aria-label="Shipment QR code ${seed}">${cells.join("")}</svg>`;
}

function driver(root) {
  const ME = Bounty.MINE, DR = Bounty.DRIVER, PRICE = {};
  const VIEWS = [["route", "My route", "map"], ["offers", "Offer inbox", "gavel"], ["pickup", "Active pickup", "pin"], ["earnings", "Earnings", "wallet"]];
  const ZC = { Cold: "z-cold", Warming: "z-warm", Hot: "z-hot" };
  const mineAuctions = () => Bounty.get().auctions.filter(a => a.eligible.includes(ME));
  const awaiting = () => mineAuctions().filter(a => !Bounty.view(a).closed && a.mine.state === "none");
  const activeJob = () => Bounty.get().auctions.filter(a => a.fulfil && a.fulfil.stage !== "paid").sort((x, y) => y.result.closedAt - x.result.closedAt)[0] || null;
  const lastDone = () => Bounty.get().auctions.filter(a => a.fulfil && a.fulfil.stage === "paid").sort((x, y) => y.fulfil.at.paid - x.fulfil.at.paid)[0] || null;
  const myLedger = () => Bounty.get().ledger.filter(l => l.winner === ME).sort((x, y) => y.at - x.at);
  const dayLabel = t => new Date(t).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
  const outcomeText = a => {
    const r = a.result, o = Bounty.outcome(a);
    if (o === "won") return `You won at ${inr(a.mine.bid)} and are paid ${inr(r.pay)} (second-lowest ${r.second != null ? inr(r.second) : "n/a"}, ceiling ${inr(a.maxB)}).`;
    if (o === "lost") return `Lost to ${r.winner} at ${inr(r.lowest)}. Your bid was ${inr(a.mine.bid)}.`;
    if (o === "declined") return `You declined. ${r.winner || "A dedicated vehicle"} took it${r.lowest ? " at " + inr(r.lowest) : ""}.`;
    if (o === "noresponse") return `The window closed before you responded. ${r.winner || "A dedicated vehicle"} took it.`;
    return "No bids: escalated to a dedicated vehicle.";
  };

  shell(root, "driver", "", "", "", `<div id="view"></div>`, { views: VIEWS, active: "route", noHead: true });
  let cur = null, active = "route", lastSig = "";
  const sigAll = () => mineAuctions().map(a => { const v = Bounty.view(a); return [a.id, a.mine.state, a.result ? 1 : 0, v.closed ? 1 : 0, a.maxB, a.ext, a.fulfil ? a.fulfil.stage : ""].join(":"); }).join("|") + "|" + Bounty.get().auctions.length;
  function badges() {
    const n = awaiting().length, j = activeJob() ? 1 : 0;
    const set = (id, k, label, ico) => { const b = $(`[data-view="${id}"]`); if (b) b.innerHTML = ic(ico) + label + (k ? `<span class="nbadge">${k}</span>` : ""); };
    set("offers", n, "Offer inbox", "gavel"); set("pickup", j, "Active pickup", "pin");
  }

  /* ================= My route ================= */
  function routeView(el, reg) {
    el.innerHTML = pageHead("My route", `${ME} · Pune → Nagpur → Kolkata · ${DR.name}`, `<span class="pill"><span class="dot live"></span>On trip</span><a class="pill" href="#offers" data-go="offers" id="rtOffers"></a>`) + `
    <div class="kpis" style="grid-template-columns:repeat(4,1fr)">
      <div class="kpi"><span class="k">Next stop</span><div class="v" id="kNext" style="font-size:26px">—</div><span class="d" id="kNextD"></span></div>
      <div class="kpi"><span class="k">Free capacity</span><div class="v num" id="kFree">85<small> kg</small></div><div class="bar thin" style="margin-top:6px"><i id="kFreeBar" style="width:17%"></i></div><span class="d" id="kFreeD">of 500 kg</span></div>
      <div class="kpi"><span class="k">Reliability</span><div class="v num">${DR.rel.toFixed(2)}</div><span class="d">score used to rank you in auctions</span></div>
      <div class="kpi"><span class="k">Bounty, last 24 h</span><div class="v num" id="kEarn">₹0</div><span class="d" id="kEarnD"></span></div>
    </div>
    <div class="grid g12">
      <section class="card s8"><div class="card-h"><h2>Assigned route</h2><span class="pill" id="drvSrc">Loading map…</span></div><div id="drvMap" class="live-map"></div><p class="leg-sub" id="drvNote" style="margin-top:12px"></p></section>
      <div class="s4" style="display:flex;flex-direction:column;gap:16px;min-width:0">
        <section class="card"><div class="card-h"><h2>Stops</h2></div><ul class="timeline" id="stops"></ul></section>
        <section class="card"><div class="card-h"><h2>Alerts</h2><small>bounty offers and updates</small></div><ul class="feed" id="feed"></ul></section>
      </div></div>`;
    const stopsBase = [["Pune hub", "Departed 17:10", "done"], ["Aurangabad", "Passed 20:30", "done"], ["Akola", "ETA 23:05", "now"], ["Nagpur hub", "ETA 01:40", ""], ["Kolkata hub", "ETA 17:40", ""]];
    function paint() {
      const a = activeJob(), n = awaiting().length, stops = stopsBase.map(s => s.slice());
      if (a) {
        const extraMin = a.detourMin, hm = 17 * 60 + 40 + extraMin, done = a.fulfil.stage !== "won";
        stops.splice(4, 0, [a.pickup.split(",")[0] + " (pickup)", `ETA 02:20 · +${a.detourKm} km, +${a.detourMin} min`, done ? "done" : ""]);
        stops[5][1] = `ETA ${pad2(Math.floor(hm / 60))}:${pad2(hm % 60)}`;
      }
      $("#stops").innerHTML = stops.map(s => `<li class="${s[2]}"><i></i><b>${s[0]}</b><span>${s[1]}</span></li>`).join("");
      const nx = stops.find(s => s[2] === "now") || stops.find(s => !s[2]);
      $("#kNext").textContent = nx[0].replace(" hub", ""); $("#kNextD").textContent = nx[1];
      const free = DR.free - (a ? a.kg : 0);
      $("#kFree").innerHTML = free + "<small> kg</small>"; $("#kFreeBar").style.width = Math.round((1 - free / DR.tot) * 100) + "%"; $("#kFreeD").textContent = a ? `${a.kg} kg reserved for ${a.ship}` : "of 500 kg";
      const paid24 = myLedger().filter(l => l.status === "paid" && l.at > Date.now() - 864e5).reduce((x, l) => x + l.paid, 0), pend = myLedger().filter(l => l.status === "pending").reduce((x, l) => x + l.paid, 0);
      $("#kEarn").textContent = inr(paid24); $("#kEarnD").textContent = pend ? inr(pend) + " pending delivery" : "all payouts released";
      $("#rtOffers").innerHTML = `${ic("gavel").replace("<svg", '<svg width="14" height="14"')} ${n ? n + " offer" + (n > 1 ? "s" : "") + " waiting" : "No offers waiting"}`;
      paintFeed();
      const ek = a ? "p" : "n"; if (ctl && ek !== extraKey) { extraKey = ek; ctl.setExtra(a ? [{ lat: 21.09, lng: 79.17, color: "var(--accent)", label: "Pickup" }] : []); }
    }
    function paintFeed() {
      const evs = Bounty.get().events.filter(e => e.d).slice(0, 6);
      $("#feed").innerHTML = evs.map(e => `<li>${e.msg}<small>${BountyUI.ago(e.t)}</small></li>`).join("") || `<li>No alerts yet.</li>`;
    }
    let ctl = null, iv, dead = false, extraKey = "";
    reg(() => { dead = true; clearInterval(iv); });
    createLiveMap($("#drvMap"), { marks: pts => [{ lat: pts[0][0], lng: pts[0][1], color: "var(--ink)", label: "Pune hub" }, { lat: pts[pts.length - 1][0], lng: pts[pts.length - 1][1], color: "var(--good)", label: "Kolkata hub" }] }).then(c => {
      if (dead) return; ctl = c;
      const fa = c.route.frac([ROUTE_WP[1][1], ROUTE_WP[1][2]]), fk = c.route.frac([ROUTE_WP[2][1], ROUTE_WP[2][2]]);
      let t = fa + .4 * (fk - fa);
      $("#drvSrc").innerHTML = c.source === "google" ? `<span class="dot"></span>Google Maps · live` : `<span class="dot" style="background:var(--warm)"></span>Leaflet · live`;
      $("#drvNote").textContent = "Your truck's position is simulated along the route; in production it is written to /live_positions/{vehicle_id} every tick.";
      paint();
      iv = setInterval(() => { c.update(t, ME); t = Math.min(.995, t + .0016); }, 2500); c.update(t, ME);
    });
    $("#view").addEventListener("click", e => { const g = e.target.closest("[data-go]"); if (g) { e.preventDefault(); go(g.dataset.go); } });
    paint();
    return { refresh: paint, tick: paintFeed };
  }

  /* ================= Offer inbox ================= */
  function offersView(el) {
    const respText = a => { const v = Bounty.view(a), n = v.ladder.filter(x => x.state !== "waiting").length; const b = v.best;
      return `${n} of ${v.ladder.length} vehicles responded · best bid ${b ? inr(b.bid) + (b.mine ? " (yours)" : "") : "none yet"}`; };
    function card(a) {
      const v = Bounty.view(a), cost = Bounty.driverCost(a), st = a.mine.state, lo = Math.round(cost.total * .8 / 10) * 10, hi = Math.max(a.maxB, lo), val = PRICE[a.id] != null ? PRICE[a.id] : Math.min(cost.total, hi);
      let body;
      if (st === "none") body = `<div class="costs"><div><span>Detour ${cost.km} km × ₹18</span><b class="num">${inr(cost.kmCost)}</b></div><div><span>Extra driving ${cost.min} min × ₹6</span><b class="num">${inr(cost.timeCost)}</b></div><div><span>Handling${a.cold ? " and cold pack" : ""}</span><b class="num">${inr(cost.handling)}</b></div><div class="tot"><span>Your cost</span><b class="num">${inr(cost.total)}</b></div></div>
        ${cost.total > a.maxB ? `<div class="auction-note">Your cost is above the ${inr(a.maxB)} ceiling, so this offer isn't worth bidding on.</div>` : `<label class="price-row" for="pr-${a.id}"><span>Your price</span><input id="pr-${a.id}" data-price="${a.id}" type="range" min="${lo}" max="${hi}" step="10" value="${val}"><b class="num" data-priceout="${a.id}">${inr(val)}</b></label>
        <p class="leg-sub">You're paid the second-lowest bid, so bidding your true cost is the best strategy.</p>`}
        <div class="actions"><button class="btn" data-act="accept" data-id="${a.id}" ${cost.total > a.maxB ? "disabled" : ""}>Accept · bid <span data-btnprice="${a.id}">${inr(val)}</span></button><button class="btn ghost" data-act="decline" data-id="${a.id}">Decline</button></div>`;
      else if (st === "bid") body = `<div class="auction-note" style="background:var(--good-soft)"><span>Bid <b class="num">${inr(a.mine.bid)}</b> placed. <span data-resp="${a.id}">${respText(a)}</span></span></div><p class="leg-sub">The window closes when every vehicle has answered or the timer ends. Lowest bid wins.</p>`;
      else body = `<div class="auction-note" style="background:var(--sunk)"><span>You declined. The offer moved to the next vehicle in the escalation ladder.</span></div>`;
      return `<article class="offer-card" data-id="${a.id}"><div class="oc-top"><div class="tags"><span class="tag">${a.id}</span><span class="tag">${a.ship}</span><span class="zone ${ZC[a.zone]}">${a.zone}</span></div>${BountyUI.ring(v.left, v.total, 58, a.id)}</div>
        <h3>${a.cargo} · ${a.kg} kg</h3>
        <div class="route-line"><span class="p fill"></span><div><b>Pickup · ${a.pickup}</b><small>+${a.detourKm} km detour · ${a.detourMin} min</small></div><span class="p"></span><div><b>Drop · ${a.drop}</b><small>${a.detourKm ? "On your route to Kolkata" : ""}</small></div></div>
        <div class="ceil"><span><small class="eyebrow nocase">Bounty ceiling (MaxBounty)</small>${a.premium ? `<br><small style="color:var(--ink-3)">includes ${inr(a.premium)} customer expedite</small>` : ""}</span><b class="num">up to ${inr(a.maxB)}</b></div>${body}</article>`;
    }
    function paint() {
      const all = mineAuctions(), open = all.filter(a => !Bounty.view(a).closed), closed = all.filter(a => Bounty.view(a).closed).sort((x, y) => y.result.closedAt - x.result.closedAt).slice(0, 6);
      const skip = Bounty.get().auctions.filter(a => !a.eligible.includes(ME) && !Bounty.view(a).closed);
      el.innerHTML = pageHead("Offer inbox", "Bounty auctions for shipments near your route. Answer before the ring runs out.", `<button class="btn sm" id="simOffer">Simulate new offer</button>`) + `
      <div class="how3"><div><i>1</i><b>Bid your true cost</b><span>Lowest bid wins the pickup.</span></div><div><i>2</i><b>Paid the second-lowest bid</b><span>Never more than the MaxBounty ceiling.</span></div><div><i>3</i><b>Decline or time out</b><span>The offer moves to the next vehicle in the ladder.</span></div></div>
      <h2 class="sub-h">Open offers <span class="tag">${open.length}</span></h2>
      ${open.length ? `<div class="offer-grid">${open.map(card).join("")}</div>` : `<div class="info-empty">${ic("gavel")}No open offers on your route right now. Dispatchers and the system open new auctions as shipments go missing. Use “Simulate new offer” to see one arrive.</div>`}
      ${closed.length ? `<h2 class="sub-h">Closed</h2><div class="card">${closed.map(a => { const o = Bounty.outcome(a); return `<div class="alt" style="grid-template-columns:auto 1fr auto"><span class="strat ${o === "won" ? "PIGGYBACK" : o === "lost" ? "DEDICATED" : ""}">${o === "won" ? "Won" : o === "lost" ? "Lost" : o === "declined" ? "Declined" : o === "noresponse" ? "Missed" : "No bids"}</span><div><b>${a.id} · ${a.ship} · ${a.cargo}</b><div class="why">${outcomeText(a)}</div></div>${o === "won" && a.fulfil.stage !== "paid" ? `<button class="btn sm" data-go="pickup">Open pickup</button>` : `<span class="num" style="color:var(--ink-3)">${BountyUI.hhmm(a.result.closedAt)}</span>`}</div>`; }).join("")}</div>` : ""}
      ${skip.length ? `<h2 class="sub-h">Not for your vehicle</h2><div class="card">${skip.map(a => `<div class="alt" style="grid-template-columns:auto 1fr auto"><span class="strat">Skipped</span><div><b>${a.id} · ${a.ship} · ${a.cargo}, ${a.kg} kg</b><div class="why">${Bounty.whyNot(a)}</div></div><span class="num" style="color:var(--ink-3)">${a.atName} → ${a.toName}</span></div>`).join("")}</div>` : ""}`;
    }
    paint();
    el.addEventListener("input", e => { const r = e.target.closest("[data-price]"); if (!r) return; const id = r.dataset.price; PRICE[id] = +r.value; $(`[data-priceout="${id}"]`, el).textContent = inr(+r.value); $(`[data-btnprice="${id}"]`, el).textContent = inr(+r.value); });
    el.addEventListener("click", e => {
      const g = e.target.closest("[data-go]"); if (g) return go(g.dataset.go);
      if (e.target.id === "simOffer") { const a = Bounty.simulateOffer(); toast(`New offer ${a.id} for ${a.ship}` + (a.eligible.includes(ME) ? "" : " (not on your route)")); return; }
      const b = e.target.closest("[data-act]"); if (!b) return; const id = b.dataset.id, a = Bounty.get().auctions.find(x => x.id === id);
      if (b.dataset.act === "accept") { const p = PRICE[id] != null ? PRICE[id] : Bounty.driverCost(a).total; if (Bounty.bid(id, p)) toast(`Bid ${inr(Math.min(a.maxB, p))} placed on ${id}. You'll hear when the window closes.`); }
      else if (Bounty.decline(id)) toast(`Declined ${id}. Offered to the next vehicle.`);
    });
    return {
      refresh: paint,
      tick() { BountyUI.updateTimers(el); $$("[data-resp]", el).forEach(n => { const a = Bounty.get().auctions.find(x => x.id === n.dataset.resp); if (a) n.textContent = respText(a); }); },
    };
  }

  /* ================= Active pickup ================= */
  function pickupView(el, reg) {
    let mapKey = "", stageKey = "";
    function paint() {
      const a = activeJob(), done = !a && lastDone(), job = a || done;
      if (!job) { el.innerHTML = pageHead("Active pickup", "Turn-by-turn directions, pickup instructions and the shipment QR appear here once you win an offer.") + `<div class="info-empty">${ic("pin")}No active pickup. Win an offer in the inbox and it appears here with directions.<br><br><button class="btn" data-go="offers">Open offer inbox</button></div>`; mapKey = ""; return; }
      const f = job.fulfil, stage = f.stage, steps = [
        ["Continue on NH-53 to Nagpur", "about 235 km from your current position (Akola)"],
        [`Exit at ${job.pickup.split(",")[0]}`, `+${job.detourKm} km detour · about ${job.detourMin} min`],
        [`Pickup: ${job.pickup}`, `Ask for ${job.ship}${job.cold ? ", cold pack must stay at 2–8 °C" : ""}. Scan the QR when loading.`],
        ["Rejoin your original route", "NH-53 via Raipur, Sambalpur and Jamshedpur"],
        [`Deliver: ${job.drop}`, "Gate 3. Scan the QR on unloading to release your payout."],
      ];
      el.innerHTML = pageHead("Active pickup", `${job.id} · ${job.ship} · ${job.cargo}, ${job.kg} kg`, `<span class="pill">${stage === "paid" ? "Delivered and paid" : stage === "loaded" ? "In transit to drop" : "Head to pickup"}</span>`) + `
      <section class="card" style="margin-bottom:16px"><div class="card-h"><h2>Progress</h2><small>${inr(job.result.pay)} payout on delivery</small></div>${BountyUI.pipeline(job)}</section>
      <div class="grid g12">
        <section class="card s7"><div class="card-h"><h2>Directions</h2><small>current location → pickup → original destination</small></div><div id="pkMap" class="live-map"></div>
          <ol class="steps" style="margin-top:16px">${steps.map((s, i) => `<li><i>${i + 1}</i><span><b>${s[0]}</b><br><small style="color:var(--ink-2)">${s[1]}</small></span></li>`).join("")}</ol></section>
        <div class="s5" style="display:flex;flex-direction:column;gap:16px;min-width:0">
          <section class="card"><div class="card-h"><h2>Shipment ${job.ship}</h2><span class="zone ${ZC[job.zone]}">${job.zone}</span></div>
            <dl class="kv" style="grid-template-columns:110px 1fr"><dt>Cargo</dt><dd>${job.cargo}, ${job.kg} kg</dd><dt>Pickup</dt><dd>${job.pickup}</dd><dt>Drop</dt><dd>${job.drop}</dd><dt>Payout</dt><dd class="num"><b>${inr(job.result.pay)}</b> <small style="color:var(--ink-3)">second-lowest bid ${job.result.second != null ? inr(job.result.second) : "n/a"}</small></dd></dl>
            ${job.cold ? `<div class="auction-note" style="background:var(--cold-soft)"><span>Cold-chain cargo: keep between 2 and 8 °C.</span></div>` : ""}</section>
          <section class="card"><div class="card-h"><h2>Scan on load</h2><small>shipment barcode</small></div><div class="qr-wrap">${fakeQR(job.ship + "-" + job.id)}<small class="num" style="color:var(--ink-3)">${job.ship} · ${job.id}</small></div>
            <div class="actions" style="margin-top:14px;flex-direction:column"><button class="btn" style="justify-content:center" data-act="loaded" data-id="${job.id}" ${stage === "won" ? "" : "disabled"}>Confirm loaded (scan QR)</button><button class="btn ghost" style="justify-content:center" data-act="delivered" data-id="${job.id}" ${stage === "loaded" ? "" : "disabled"}>Mark delivered at ${job.toName}</button></div></section>
        </div></div>`;
      const key = job.id;
      if (mapKey !== key) mapKey = key;
      const m = createNetworkMap($("#pkMap"), { heat: false, cands: false, legs: false, labels: false, hubs: false });
      m.setRoutePoints([[20.7002, 77.0082], [21.09, 79.17], [22.5726, 88.3639]], [{ lat: 20.7002, lng: 77.0082, color: "var(--ink)", label: "You", truck: true }, { lat: 21.09, lng: 79.17, color: "var(--accent)", label: "Pickup" }, { lat: 22.5726, lng: 88.3639, color: "var(--good)", label: job.toName }]);
      const th = () => m.redraw(); document.addEventListener("themechange", th); reg(() => document.removeEventListener("themechange", th));
    }
    paint();
    el.addEventListener("click", e => {
      const g = e.target.closest("[data-go]"); if (g) return go(g.dataset.go);
      const b = e.target.closest("[data-act]"); if (!b || b.disabled) return;
      if (Bounty.advance(b.dataset.id, b.dataset.act)) toast(b.dataset.act === "loaded" ? "Loaded. Head for the drop." : "Delivered. Your bounty payout has been released.");
    });
    return { refresh() { const j = activeJob() || lastDone(); const k = (j ? j.id + ":" + j.fulfil.stage : "none"); if (k !== stageKey) { stageKey = k; paint(); } }, tick() { } , init() { const j = activeJob() || lastDone(); stageKey = j ? j.id + ":" + j.fulfil.stage : "none"; } };
  }

  /* ================= Earnings ================= */
  function earningsView(el) {
    function paint() {
      const L = myLedger(), paid = L.filter(l => l.status === "paid"), pend = L.filter(l => l.status === "pending"), wk = paid.filter(l => l.at > Date.now() - 7 * 864e5);
      const sum = a => a.reduce((x, l) => x + l.paid, 0), avg = paid.length ? sum(paid) / paid.length : 0;
      const days = [...Array(7)].map((_, i) => { const d0 = new Date(); d0.setHours(0, 0, 0, 0); const s = d0.getTime() - (6 - i) * 864e5; return { s, label: new Date(s).toLocaleDateString("en-IN", { weekday: "short" }), v: paid.filter(l => l.at >= s && l.at < s + 864e5).reduce((x, l) => x + l.paid, 0) }; });
      const mx = Math.max(700, ...days.map(d => d.v)), last = L.find(l => Bounty.get().auctions.find(a => a.id === l.id));
      const la = last && Bounty.get().auctions.find(a => a.id === last.id);
      el.innerHTML = pageHead("Earnings", "Every bounty payment, with the bid you placed and what you were actually paid.", `<span class="pill">Paid on delivery</span>`) + `
      <div class="kpis" style="grid-template-columns:repeat(4,1fr)">
        <div class="kpi feat"><div><span class="k">Paid, last 7 days</span><div class="v num">${inr(sum(wk))}</div><span class="d">${wk.length} job${wk.length === 1 ? "" : "s"}</span></div></div>
        <div class="kpi"><span class="k">Pending delivery</span><div class="v num">${inr(sum(pend))}</div><span class="d">${pend.length ? "released when you mark delivered" : "nothing pending"}</span></div>
        <div class="kpi"><span class="k">Jobs completed</span><div class="v num">${paid.length}</div><span class="d">all time</span></div>
        <div class="kpi"><span class="k">Average bounty</span><div class="v num">${inr(avg)}</div><span class="d">per completed job</span></div>
      </div>
      <div class="grid g12">
        <section class="card s7"><div class="card-h"><h2>Last 7 days</h2><small>bounty paid per day</small></div>
          <svg class="chart" viewBox="0 0 520 190" role="img" aria-label="Bounty paid per day over the last seven days">${[0, 350, 700].map(v => `<line class="grid-l" x1="34" x2="520" y1="${160 - v / mx * 130}" y2="${160 - v / mx * 130}"/><text x="28" y="${164 - v / mx * 130}" text-anchor="end">${v}</text>`).join("")}
            ${days.map((d, i) => { const h = d.v / mx * 130, x = 46 + i * 68; return `<rect x="${x}" y="${160 - h}" width="40" height="${Math.max(h, 2)}" rx="6" fill="${d.v ? "var(--accent)" : "var(--sunk)"}"/><text x="${x + 20}" y="180" text-anchor="middle">${d.label}</text>${d.v ? `<text class="val" x="${x + 20}" y="${152 - h}" text-anchor="middle">${d.v}</text>` : ""}`; }).join("")}</svg></section>
        <section class="card s5"><div class="card-h"><h2>Why you're paid that amount</h2><small>Vickrey pricing</small></div>
          ${la && la.result && la.result.winner === ME ? `<div class="pay-bars"><div class="row"><span>Your bid</span><div class="bar"><i style="width:${Math.round(la.mine.bid / la.maxB * 100)}%;background:var(--ink-3)"></i></div><span class="num">${inr(la.mine.bid)}</span></div><div class="row"><span>Paid (2nd-lowest)</span><div class="bar"><i style="width:${Math.round(la.result.pay / la.maxB * 100)}%"></i></div><span class="num">${inr(la.result.pay)}</span></div><div class="row"><span>MaxBounty cap</span><div class="bar"><i style="width:100%;background:var(--good)"></i></div><span class="num">${inr(la.maxB)}</span></div></div><p class="leg-sub" style="margin-top:12px">${la.id}: you bid your true cost, won, and were paid the second-lowest bid.</p>` : `<p class="leg-sub">Payment = min(second-lowest bid, MaxBounty). Win an auction and the bid, payment and ceiling for it show here.</p>`}</section>
        <section class="card s12"><div class="card-h"><h2>Payment ledger</h2><small>${L.length} entries</small></div><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Auction</th><th>Route</th><th>Your bid</th><th>Paid</th><th>Status</th></tr></thead><tbody>${L.map(l => `<tr><td>${dayLabel(l.at)}</td><td><b>${l.id}</b> · ${l.ship}</td><td>${l.route || "—"}</td><td class="num">${inr(l.bid)}</td><td class="num"><b>${inr(l.paid)}</b></td><td><span class="zone ${l.status === "paid" ? "" : "z-warm"}" style="${l.status === "paid" ? "background:var(--good-soft);color:var(--good)" : ""}">${l.status === "paid" ? "Paid" : "Pending delivery"}</span></td></tr>`).join("")}</tbody></table></div></section>
      </div>`;
    }
    paint(); return { refresh: paint, tick() { } };
  }

  /* ================= router ================= */
  const VIEW_FNS = { route: routeView, offers: offersView, pickup: pickupView, earnings: earningsView };
  let cleanups = [];
  function go(v) {
    cleanups.forEach(f => { try { f(); } catch (e) { } }); cleanups = []; active = v;
    $$("[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === v));
    $("#view").innerHTML = ""; const el = $("#view"), clone = el.cloneNode(false); el.replaceWith(clone);
    cur = VIEW_FNS[v](clone, f => cleanups.push(f)); if (cur.init) cur.init();
    history.replaceState(null, "", "#" + v); window.scrollTo(0, 0); badges(); lastSig = sigAll();
  }
  $$("[data-view]").forEach(b => b.addEventListener("click", () => go(b.dataset.view)));
  Bounty.onChange(() => { if (cur) { cur.refresh(); badges(); lastSig = sigAll(); } });
  const iv = setInterval(() => {
    Bounty.tick();                                   /* settles due auctions; fires onChange when something changed */
    const s = sigAll(); if (s !== lastSig) { lastSig = s; cur && cur.refresh(); }
    badges(); cur && cur.tick && cur.tick();
  }, 1000);
  onLeave(() => clearInterval(iv));
  go(VIEWS.some(v => v[0] === location.hash.slice(1)) ? location.hash.slice(1) : "route");
}
