/* Bounty market (E5): a single store shared by the Admin, Dispatcher, Driver and Customer portals.
   - Reverse auction among vehicles already heading that way; lowest bid wins.
   - Vickrey payment:  Payment = min(second_lowest_bid, MaxBounty)
   - Ceiling:          MaxBounty = min(λ × Δt_saved + customer premium, C_dedicated − C_overhead)
   - Escalation ladder: an offer that is declined or times out moves to the next vehicle in the ladder.
   State lives in localStorage so separate portals (and tabs) see the same auctions; in production this is
   Firestore /bounty_offers/{auction_id} plus FastAPI POST /auctions/{id}/bid. */
const Bounty = (() => {
  const KEY = "maarg-bounty-v2", MINE = "Truck 12", OVERHEAD = 120, DT_SAVED = 6.5, listeners = new Set();
  const FLEET = [
    { veh: "Truck 12", kind: "owned", route: ["PNQ", "NAG", "KOL"], free: 85, driver: true },
    { veh: "Truck 19", kind: "owned", route: ["NAG", "KOL"], free: 60 }, { veh: "Truck 07", kind: "owned", route: ["AMD", "DEL"], free: 310 },
    { veh: "Truck 25", kind: "owned", route: ["DEL", "LKO"], free: 205 }, { veh: "Truck 28", kind: "owned", route: ["KOL", "GAU"], free: 390 },
    { veh: "Truck 22", kind: "owned", route: ["BPL", "NAG"], free: 140 }, { veh: "Truck 14", kind: "owned", route: ["HYD", "NAG"], free: 95 },
    { veh: "Truck 08", kind: "owned", route: ["JAI", "DEL"], free: 275 }, { veh: "Van 9", kind: "owned", route: ["BLR", "MAA"], free: 55 },
    { veh: "Van 2", kind: "owned", route: ["DEL", "CHD"], free: 150 }, { veh: "Truck 31", kind: "third", route: ["BOM", "AMD"], free: 240 },
    { veh: "Van 4", kind: "third", route: ["HYD", "BLR"], free: 120 }, { veh: "Truck 03", kind: "third", route: ["LKO", "PAT"], free: 170 },
    { veh: "Truck 16", kind: "third", route: ["BLR", "COK"], free: 260 }, { veh: "Truck 33", kind: "third", route: ["SUR", "PNQ"], free: 190 },
    { veh: "Truck 05", kind: "third", route: ["KOL", "BBI"], free: 210 },
  ];
  const fleet = v => FLEET.find(f => f.veh === v);
  const DRIVER = { veh: MINE, name: "Suresh Patil", route: ["PNQ", "NAG", "KOL"], free: 85, tot: 500, rel: .93 };
  const hash = s => { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
  const parseKg = c => { const m = /(\d+)\s*kg/.exec(c || ""); return m ? +m[1] : 50; };
  const T = () => Date.now();
  let mem = null;

  /* ---------- storage ---------- */
  function read() { try { const r = localStorage.getItem(KEY); if (r) return JSON.parse(r); } catch (e) { } return mem ? JSON.parse(JSON.stringify(mem)) : null; }
  function notify() { listeners.forEach(f => { try { f(); } catch (e) { } }); }
  function write(d) { d.rev = (d.rev || 0) + 1; mem = d; try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (e) { } notify(); }
  window.addEventListener("storage", e => { if (e.key === KEY) notify(); });
  function db() { let d = read(); if (!d || d.v !== 2) { d = seed(); write(d); } return d; }
  function mutate(fn) { const d = db(); const r = fn(d); write(d); return r; }
  const ev = (d, k, msg, id, forDriver) => d.events.unshift({ t: T(), k, msg, id, d: !!forDriver });

  /* ---------- building auctions ---------- */
  function eligibleFor(at, kg) {
    return FLEET.filter(f => f.route.includes(at) && f.free >= kg).sort((a, b) => (a.kind === "owned" ? 0 : 1) - (b.kind === "owned" ? 0 : 1) || b.free - a.free).map(f => f.veh);
  }
  function simFor(vehs, ship, kg, maxB) {
    return vehs.filter(v => v !== MINE).map((v, i) => { const h = hash(ship + v), dec = h % 7 === 0; return { veh: v, bid: dec ? null : Math.min(maxB, Math.round((200 + kg * 1.2 + (h % 170)) / 10) * 10), at: 20 + (h % 70) + i * 9 }; });
  }
  function ceiling(a) { return Math.round(Math.min(a.lam * DT_SAVED + (a.premium || 0), a.ded - OVERHEAD)); }
  function build(id, s, o = {}) {
    const p = planFor(s), ded = p.opts.find(x => x.strat === "DEDICATED"), kg = o.kg || parseKg(s.cargo), h = hash(s.id);
    /* live plans may have no DEDICATED option yet: fall back to twice the best plan as the dedicated benchmark */
    const dedCost = ded ? ded.c + ded.hand : Math.max(1000, 2 * ((p.opts[0] && p.opts[0].c) || 500));
    const a = {
      id, ship: s.id, cargo: s.cargo.replace(/,\s*\d+\s*kg/, ""), kg, zone: zoneOf(s.T)[0], lam: Math.round(p.lam), at: s.at, atName: hub(s.at).name, toName: hub(s.to).name,
      pickup: o.pickup || hub(s.at).name + " sorting centre, Gate " + "ABC"[h % 3], drop: o.drop || hub(s.to).name + " hub", cold: /pharma|cold|perish|medical/i.test(s.cargo),
      detourKm: o.detourKm != null ? o.detourKm : 3 + (h % 6), detourMin: o.detourMin != null ? o.detourMin : 12 + (h % 12),
      openedAt: o.openedAt || T(), winSec: o.win || 300, ext: 0, premium: 0, ded: Math.round(dedCost), source: o.source || "system", forced: null,
      mine: { state: "none" }, result: null, fulfil: null,
    };
    a.maxB = o.maxB || ceiling(a);
    a.eligible = o.eligible || eligibleFor(s.at, kg);
    a.sim = o.sim || simFor(a.eligible, s.id, kg, a.maxB);
    return a;
  }
  function seed() {
    const t = T(), S = id => SHIPMENTS.find(x => x.id === id);
    const d = { v: 2, rev: 0, seq: 1045, auctions: [], ledger: [], events: [] };
    /* sample fixtures only: skipped when the page holds live shipments that don't include them */
    const ok = s => s && hub(s.at) && hub(s.to);
    const push = (id, s, o) => { if (ok(s)) { try { d.auctions.push(build(id, s, o)); } catch (e) { } } };
    if (ok(S("S204"))) d.auctions.push(build("A-1042", S("S204"), { pickup: "Nagpur bypass, km 12", drop: "Kolkata hub", detourKm: 6, detourMin: 22, openedAt: t - 25000, source: "dispatcher",
      eligible: ["Truck 12", "Truck 19", "Truck 31", "Van 4"], sim: [{ veh: "Truck 31", bid: 560, at: 40 }, { veh: "Van 4", bid: 620, at: 75 }, { veh: "Truck 19", bid: 710, at: 110 }] }));
    push("A-1043", S("S231"), { openedAt: t - 40000 });
    push("A-1044", S("S263"), { pickup: "Nagpur sorting centre, Gate C", drop: "Kolkata hub", detourKm: 4, detourMin: 15, openedAt: t - 15000,
      sim: [{ veh: "Truck 22", bid: 450, at: 35 }, { veh: "Truck 14", bid: 520, at: 70 }] });
    push("A-1045", S("S271"), { openedAt: t - 30000 });
    [["A-1041", "S190", "Van 9", 470, 1920], ["A-1040", "S077", "Truck 25", 350, 1780], ["A-1039", "S402", "Truck 07", 610, 2340], ["A-1038", "S118", "Truck 31", 520, 2050], ["A-1037", "S330", "Truck 28", 680, 2610], ["A-1036", "S099", "Truck 22", 390, 1850]]
      .forEach((r, i) => d.ledger.push({ id: r[0], ship: r[1], winner: r[2], paid: r[3], ded: r[4], at: t - (i + 1) * 38 * 60000, by: "sim", bid: r[3] - 40, status: "paid", route: "" }));
    [["A-1031", "S118", "Mumbai → Ahmedabad", 420, 380, 1], ["A-1027", "S402", "Ahmedabad → Delhi", 690, 640, 3], ["A-1022", "S077", "Delhi → Jaipur", 350, 330, 5]]
      .forEach(r => d.ledger.push({ id: r[0], ship: r[1], winner: MINE, paid: r[3], ded: r[3] * 4, at: t - r[5] * 864e5, by: "driver", bid: r[4], status: "paid", route: r[2] }));
    if (d.auctions.some(a => a.id === "A-1042")) ev(d, "offer", "Auction A-1042 opened for S204 · 4 vehicles eligible", "A-1042", true);
    if (d.auctions.some(a => a.id === "A-1044")) ev(d, "offer", "Auction A-1044 opened for S263 · Truck 12 is eligible", "A-1044", true);
    return d;
  }

  /* ---------- derived state ---------- */
  function view(a, t = T()) {
    const winEnd = a.openedAt + (a.winSec + (a.ext || 0)) * 1000;
    const ladder = a.eligible.map(vh => {
      if (vh === MINE) return { veh: vh, mine: true, kind: "owned", state: a.mine.state === "bid" ? "bid" : a.mine.state === "declined" ? "declined" : "waiting", bid: a.mine.bid, at: a.mine.at || 0 };
      const e = a.sim.find(x => x.veh === vh), at = e ? a.openedAt + e.at * 1000 : Infinity;
      return { veh: vh, kind: (fleet(vh) || {}).kind || "third", state: e && at <= t ? (e.bid == null ? "declined" : "bid") : "waiting", bid: e ? e.bid : null, at };
    });
    const all = ladder.length > 0 && ladder.every(x => x.state !== "waiting");
    let closeAt = winEnd; if (a.forced) closeAt = Math.min(closeAt, a.forced);
    if (all) closeAt = Math.min(closeAt, Math.max(...ladder.map(x => x.at || 0)));
    if (!ladder.length) closeAt = Math.min(closeAt, a.openedAt + 3000);
    const closed = !!a.result || t >= closeAt, tc = a.result ? a.result.closedAt : Math.min(t, closeAt);
    const shown = ladder.map(x => (x.state === "bid" && x.at > tc) ? { ...x, state: "waiting" } : x);
    const bids = shown.filter(x => x.state === "bid").sort((x, y) => x.bid - y.bid || x.at - y.at);
    const second = bids[1] ? bids[1].bid : null, pay = bids.length ? Math.min(second != null ? second : a.maxB, a.maxB) : 0;
    const me = a.mine.state === "bid" ? bids.findIndex(x => x.mine) : -1;
    return { a, t, ladder: shown, bids, best: bids[0] || null, second, pay, closed, closeAt, winEnd, left: Math.max(0, Math.ceil((winEnd - t) / 1000)), total: a.winSec + (a.ext || 0), mineRank: me,
      sig: [a.id, a.mine.state, a.result ? 1 : 0, closed ? 1 : 0, bids.length, shown.filter(x => x.state === "declined").length, a.maxB, a.ext, a.fulfil ? a.fulfil.stage : ""].join("|") };
  }
  function outcome(a) {   /* how this auction ended for the driver's vehicle */
    if (!a.result) return "open";
    if (a.result.winner == null) return "nobids";
    if (a.result.winner === MINE) return "won";
    return a.mine.state === "bid" ? "lost" : a.mine.state === "declined" ? "declined" : "noresponse";
  }

  /* ---------- engine ---------- */
  function settle(d, a) {
    if (a.result) return; const v = view(a); if (!v.closed) return;
    const w = v.best, id = a.id;
    a.result = { closedAt: v.closeAt, winner: w ? w.veh : null, pay: v.pay, second: v.second, lowest: w ? w.bid : null, bids: v.bids.length };
    if (!w) { ev(d, "closed", `${id} closed with no bids → escalated to a dedicated vehicle (${inr(a.ded)})`, id, a.eligible.includes(MINE)); return; }
    const byDriver = w.veh === MINE;
    d.ledger.unshift({ id, ship: a.ship, winner: w.veh, paid: v.pay, ded: a.ded, at: v.closeAt, by: byDriver ? "driver" : "sim", bid: w.bid, status: byDriver ? "pending" : "paid", route: `${a.atName} → ${a.toName}` });
    if (byDriver) a.fulfil = { stage: "won", at: { won: v.closeAt } };
    ev(d, "closed", `${id} closed: ${w.veh} won at ${inr(w.bid)} and is paid ${inr(v.pay)} (second-lowest ${v.second != null ? inr(v.second) : "n/a, MaxBounty applies"}, cap ${inr(a.maxB)})`, id, a.eligible.includes(MINE));
  }
  function tick() {
    const d = read() || db(); if (!d.auctions.some(a => !a.result && view(a).closed)) return false;
    mutate(dd => dd.auctions.forEach(a => settle(dd, a))); return true;
  }
  const find = (d, id) => d.auctions.find(a => a.id === id);

  const api = {
    MINE, DRIVER, FLEET, KEY, DT_SAVED, OVERHEAD,
    get() { return db(); }, rev() { return db().rev; }, view, outcome, ceiling, tick,
    onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    forShip(id) { return db().auctions.find(a => a.ship === id && !a.result) || db().auctions.filter(a => a.ship === id).pop() || null; },
    openCount() { return db().auctions.filter(a => !view(a).closed).length; },
    driverCost(a) { const km = a.detourKm * 18, mn = a.detourMin * 6, hd = 240; return { km: a.detourKm, min: a.detourMin, kmCost: km, timeCost: mn, handling: hd, total: Math.round((km + mn + hd) / 10) * 10 }; },
    whyNot(a) {
      const hubs = DRIVER.route; if (!hubs.includes(a.at)) return `Pickup in ${a.atName} isn't on your route`;
      if (a.kg > DRIVER.free) return `Needs ${a.kg} kg; you have ${DRIVER.free} kg free`; return "Not in your eligible group";
    },
    /* open (or reuse) an auction for a misplaced shipment: dispatcher approval, admin, or a new disruption */
    openFor(s, source) {
      const ex = db().auctions.find(a => a.ship === s.id && !view(a).closed); if (ex) return ex;
      return mutate(d => { const a = build("A-" + (++d.seq), s, { source }); d.auctions.unshift(a);
        ev(d, "offer", `Auction ${a.id} opened for ${a.ship} · MaxBounty ${inr(a.maxB)} · ${a.eligible.length} eligible vehicle${a.eligible.length === 1 ? "" : "s"}${a.eligible.length ? "" : " (none: dedicated vehicle)"}`, a.id, a.eligible.includes(MINE)); return a; });
    },
    simulateOffer() {
      const busy = new Set(db().auctions.filter(a => !view(a).closed).map(a => a.ship));
      let s = DRIVER_POOL.find(x => !busy.has(x.id) && !db().auctions.some(a => a.ship === x.id));
      if (!s) s = DRIVER_POOL[hash(String(T())) % DRIVER_POOL.length], s = { ...s, id: "S" + (300 + (hash(String(T())) % 90)) };
      if (!SHIPMENTS.some(x => x.id === s.id)) SHIPMENTS.push({ ...s });
      return api.openFor(s, "system");
    },
    bid(id, price) {
      return mutate(d => { const a = find(d, id), v = view(a); if (!a || v.closed || a.mine.state !== "none") return false;
        a.mine = { state: "bid", bid: Math.max(10, Math.min(a.maxB, Math.round(price / 10) * 10)), at: T() };
        ev(d, "bid", `${MINE} (${DRIVER.name}) bid ${inr(a.mine.bid)} on ${id}`, id, true); return true; });
    },
    decline(id) {
      return mutate(d => { const a = find(d, id), v = view(a); if (!a || v.closed || a.mine.state !== "none") return false;
        a.mine = { state: "declined", at: T() }; ev(d, "decline", `${MINE} declined ${id} → offered to the next vehicle in the ladder`, id, true); return true; });
    },
    advance(id, stage) {
      return mutate(d => { const a = find(d, id); if (!a || !a.fulfil) return false; const f = a.fulfil, t = T();
        if (stage === "loaded" && f.stage === "won") { f.stage = "loaded"; f.at.loaded = t; ev(d, "stage", `${MINE} loaded ${a.ship} at ${a.pickup} (QR scanned)`, id, true); return true; }
        if (stage === "delivered" && f.stage === "loaded") { f.stage = "paid"; f.at.delivered = t; f.at.paid = t;
          const row = d.ledger.find(x => x.id === id && x.winner === MINE); if (row) { row.status = "paid"; row.paidAt = t; }
          ev(d, "paid", `${MINE} delivered ${a.ship} to ${a.drop} · payout ${inr(a.result.pay)} released`, id, true); return true; }
        return false; });
    },
    extend(id, sec) { return mutate(d => { const a = find(d, id); if (!a || view(a).closed) return false; a.ext = (a.ext || 0) + sec; a.forced = null; ev(d, "admin", `Admin extended ${id} by ${Math.round(sec / 60)} min`, id, a.eligible.includes(MINE)); return true; }); },
    closeNow(id) { return mutate(d => { const a = find(d, id); if (!a || view(a).closed) return false; a.forced = T(); ev(d, "admin", `Admin closed ${id} early`, id, a.eligible.includes(MINE)); settle(d, a); return true; }); },
    /* the customer's expedite amount is an input to MaxBounty, never an override */
    expedite(shipId, premium) {
      return mutate(d => { const a = d.auctions.find(x => x.ship === shipId && !view(x).closed); if (!a) return null; a.premium = premium; a.maxB = ceiling(a);
        ev(d, "premium", `Customer expedite of ${inr(premium)} raised MaxBounty on ${a.id} to ${inr(a.maxB)}`, a.id, a.eligible.includes(MINE)); return a; });
    },
    reset() { mem = null; try { localStorage.removeItem(KEY); } catch (e) { } write(seed()); },
  };
  return api;
})();

/* ---------- shared UI helpers ---------- */
const BountyUI = {
  ring(left, total, size = 62, id = "") {
    const r = size / 2 - 5, c = 2 * Math.PI * r, f = total ? Math.max(0, Math.min(1, left / total)) : 0;
    return `<div class="ring" data-ring="${id}" style="width:${size}px;height:${size}px"><svg viewBox="0 0 ${size} ${size}"><circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--line)" stroke-width="5"/><circle data-ringfg cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--accent)" stroke-width="5" stroke-linecap="round" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${(c * (1 - f)).toFixed(1)}"/></svg><span class="num" data-ringtxt>${fmtCd(left)}</span></div>`;
  },
  hhmm(t) { const d = new Date(t); return pad2(d.getHours()) + ":" + pad2(d.getMinutes()); },
  ago(t) { const s = Math.max(0, Math.round((Date.now() - t) / 1000)); return s < 60 ? "just now" : s < 3600 ? Math.round(s / 60) + " min ago" : s < 86400 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " d ago"; },
  pipeline(a) {
    const f = a.fulfil; if (!f) return "";
    const steps = [["won", "Won"], ["loaded", "Loaded"], ["delivered", "Delivered"], ["paid", "Paid"]], idx = { won: 0, loaded: 1, paid: 3 }[f.stage];
    return `<div class="pipeline" role="list">${steps.map((s, i) => { const done = i <= idx, t = f.at[s[0]]; return `<div role="listitem" class="${done ? "done" : ""} ${i === idx + 1 ? "next" : ""}"><i>${done ? "✓" : i + 1}</i><b>${s[1]}</b><small>${t ? BountyUI.hhmm(t) : "—"}</small></div>`; }).join("")}</div>`;
  },
  /* the auction monitor: eligible vehicles in ladder order, bids as they arrive, countdown, winner highlight */
  monitor(a, o = {}) {
    const v = Bounty.view(a), r = a.result;
    const rows = v.ladder.map((x, i) => {
      const win = r && r.winner === x.veh, low = !r && v.best && v.best.veh === x.veh;
      const label = `<b>${x.veh}${x.mine ? ' <span class="tag">driver app</span>' : ""}</b><br><small style="color:var(--ink-3)">${x.mine ? Bounty.DRIVER.name + " · " : ""}${x.kind === "owned" ? "Owned" : "Third-party"} · rung ${i + 1}</small>`;
      if (x.state === "bid") return `<div class="bid ${win ? "win" : ""}"><span>${label}</span><span class="num"><b>${inr(x.bid)}</b></span><span class="zone" style="${win ? "background:var(--good-soft);color:var(--good)" : low ? "background:var(--accent-soft);color:var(--accent)" : "background:var(--sunk);color:var(--ink-2)"}">${win ? "Winner" : low ? "Lowest" : "Bid"}</span></div>`;
      if (x.state === "declined") return `<div class="bid wait"><span>${label}</span><span>Declined</span><span class="zone" style="background:var(--sunk);color:var(--ink-3)">Next rung</span></div>`;
      return `<div class="bid wait"><span>${label}</span><span>${v.closed ? "No response" : "Waiting…"}</span><span></span></div>`;
    }).join("") || `<div class="info-empty">No eligible vehicle. MAARG will dispatch a dedicated vehicle.</div>`;
    let out = "";
    if (r && r.winner) out = `<div class="auction-note" style="background:var(--good-soft)"><span><b>${r.winner}</b> wins at ${inr(r.lowest)} and is paid the second-lowest bid ${r.second != null ? inr(r.second) : "(only one bid, so the MaxBounty applies)"}, capped at ${inr(a.maxB)}.</span><span class="num"><b>${inr(r.pay)}</b></span></div>`;
    else if (r) out = `<div class="auction-note"><span>No bids. The offer escalated to a dedicated vehicle.</span><span class="num"><b>${inr(a.ded)}</b></span></div>`;
    return `<div data-mon="${a.id}"><div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap"><div><small class="eyebrow">${v.closed ? "Auction closed" : "Closes in"}</small><div class="timer num" data-left="${a.id}">${v.closed ? "00:00" : fmtCd(v.left)}</div></div><div style="text-align:right"><small class="eyebrow nocase">MaxBounty</small><div class="num" style="font-family:var(--f-display);font-size:22px">${inr(a.maxB)}</div></div></div>
      <p class="leg-sub" style="margin:2px 0 12px">min(λ × Δt + customer premium, C_dedicated − overhead) · λ ${inr(a.lam)}/hr · Δt ${Bounty.DT_SAVED} h${a.premium ? " · premium " + inr(a.premium) : ""}</p>
      <p class="explain-h" style="margin-top:0">Eligible vehicles · escalation ladder</p>${rows}${out}
      ${a.fulfil ? `<p class="explain-h">Driver fulfilment</p>${BountyUI.pipeline(a)}` : ""}${o.controls ? o.controls(a, v) : ""}</div>`;
  },
  /* keep countdowns/rings live without repainting */
  updateTimers(root) {
    $$("[data-left]", root).forEach(n => { const a = Bounty.get().auctions.find(x => x.id === n.dataset.left); if (a) { const v = Bounty.view(a); n.textContent = v.closed ? "00:00" : fmtCd(v.left); } });
    $$("[data-ring]", root).forEach(n => { const a = Bounty.get().auctions.find(x => x.id === n.dataset.ring); if (!a) return; const v = Bounty.view(a), fg = $("[data-ringfg]", n), c = +fg.getAttribute("stroke-dasharray");
      fg.setAttribute("stroke-dashoffset", (c * (1 - (v.closed ? 0 : v.left / v.total))).toFixed(1)); $("[data-ringtxt]", n).textContent = v.closed ? "—" : fmtCd(v.left); });
  },
};
