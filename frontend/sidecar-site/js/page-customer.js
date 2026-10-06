/* Customer portal: shipment timeline (origin · current · destination), live map, temperature, expedite */
function gaugeSVG(T) {
  const cx = 120, cy = 116, r = 92, pt = (v, rr = r) => { const th = Math.PI * (1 - v / 100); return [cx + rr * Math.cos(th), cy - rr * Math.sin(th)]; };
  const arc = (a, b, col) => { const p0 = pt(a), p1 = pt(b); return `<path d="M${p0[0].toFixed(1)} ${p0[1].toFixed(1)} A${r} ${r} 0 0 1 ${p1[0].toFixed(1)} ${p1[1].toFixed(1)}" fill="none" stroke="${col}" stroke-width="16" stroke-linecap="butt"/>`; };
  const n = pt(T, r - 24);
  return `<svg viewBox="0 0 240 142" role="img" aria-label="Temperature ${Math.round(T)} of 100" style="width:100%;max-width:280px;margin:0 auto">
    ${arc(0, 33.5, "var(--cold)")}${arc(33.5, 66.5, "var(--warm)")}${arc(66.5, 100, "var(--hot)")}
    <line x1="${cx}" y1="${cy}" x2="${n[0].toFixed(1)}" y2="${n[1].toFixed(1)}" stroke="var(--ink)" stroke-width="4" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="8" fill="var(--ink)"/>
    <text x="${pt(0)[0] + 2}" y="${cy + 18}" text-anchor="start" style="font:11px Outfit,sans-serif;fill:var(--ink-3)">Cold</text><text x="${pt(100)[0] - 2}" y="${cy + 18}" text-anchor="end" style="font:11px Outfit,sans-serif;fill:var(--ink-3)">Hot</text></svg>`;
}
function sparkSVG(vals) {
  const W = 260, H = 64, y = v => H - 4 - (v / 10) * (H - 8), x = i => 2 + i * (W - 4) / (vals.length - 1);
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%" role="img" aria-label="Cargo temperature over the last ${vals.length} readings, safe range 2 to 8 degrees Celsius">
    <rect x="0" y="${y(8)}" width="${W}" height="${y(2) - y(8)}" fill="var(--good-soft)" rx="6"/>
    <polyline fill="none" stroke="var(--accent)" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" points="${vals.map((v, i) => x(i).toFixed(1) + "," + y(v).toFixed(1)).join(" ")}"/>
    <circle cx="${x(vals.length - 1)}" cy="${y(vals[vals.length - 1])}" r="4" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/></svg>`;
}

function customer(root) {
  const s = SHIPMENTS.find(x => x.id === MAARG.trackedId());
  if (!s) { shell(root, "customer", "Track shipment", "", "", `<div class="info-empty">${ic("route")}No shipment to track yet. Once a shipment is in transit it appears here.</div>`); return; }
  const p = planFor(s), best = p.opts[0];
  const comp = [["Base", 18], ["Time", 12], ["Delay", 9], ["Cascade", 6]]; /* T_base + T_time + T_delay + T_cascade = 45 */
  const fmtT = h => { const t = 19.33 + h, d = Math.floor(t / 24), m = Math.round((t % 24) * 60); return (d ? "Tomorrow " : "Today ") + pad2(Math.floor(m / 60) % 24) + ":" + pad2(m % 60); };
  let cargo = [4.4, 4.5, 4.3, 4.6, 4.8, 4.7, 4.5, 4.4, 4.6, 4.9, 4.7, 4.6];

  const body = `
  <div class="banner">${ic("alert")}<div><b style="font-family:var(--f-display);font-weight:500">Your shipment was found in Nagpur, not on the Kolkata truck.</b><br><span style="color:var(--ink-2)">MAARG recovered it on a vehicle already heading that way. Revised arrival <b id="etaTop">${fmtT(best.h)}</b>.</span></div></div>

  <section class="card" aria-label="Shipment route summary" style="margin-bottom:16px">
    <div class="route-strip">
      <div class="rs-node"><small>Origin</small><b>Pune hub</b><span>Departed 09:10</span></div>
      <div class="rs-node cur"><small>Current · live</small><b id="curPlace">Near Nagpur</b><span id="curSub">—</span></div>
      <div class="rs-node"><small>Destination</small><b>Kolkata hub</b><span>ETA <span id="etaDest">${fmtT(best.h)}</span></span></div>
    </div>
    <div class="rail" role="progressbar" aria-label="Distance covered" aria-valuemin="0" aria-valuemax="100" id="railBar"><i id="railFill"></i></div>
    <div class="rail-l"><span id="pctDone">0% covered</span><span id="kmLeft">— km to go</span></div>
  </section>

  <div class="grid g12">
    <section class="card s8" aria-label="Live map">
      <div class="card-h"><h2>Live map</h2><span class="pill" id="mapSrc">Loading map…</span></div>
      <div id="liveMap" class="live-map"></div>
      <p class="leg-sub" id="mapNote" style="margin-top:12px"></p>
    </section>
    <div class="s4" style="display:flex;flex-direction:column;gap:16px;min-width:0">
      <section class="card"><div class="card-h"><h2>Urgency temperature</h2><small>how hard MAARG works on it</small></div>
        ${gaugeSVG(s.T)}
        <div style="text-align:center;margin-top:-6px"><span class="zone z-warm">Warming</span> <b class="num" style="font-family:var(--f-display);font-size:26px;font-weight:300;margin-left:6px">T ${s.T}</b></div>
        <dl class="kv" style="grid-template-columns:auto 1fr;margin:14px 0 8px"><dt>Urgency</dt><dd class="num"><b>${inr(p.lam)}</b> per hour of delay</dd></dl>
        <div style="display:grid;gap:8px">${comp.map(c => `<div class="cap-line"><span style="width:62px;font-size:13px;color:var(--ink-2)">T_${c[0].toLowerCase()}</span><div class="bar thin"><i style="width:${c[1] / 25 * 100}%"></i></div><span class="num" style="width:26px;text-align:right;font-size:13px">+${c[1]}</span></div>`).join("")}</div>
        <p class="leg-sub" style="margin-top:10px">T = clamp(0, 100, T_base + T_time + T_delay + T_cascade)<br>λ = SLA penalty × (1 + T / 50)</p></section>
      <section class="card"><div class="card-h"><h2>Cargo temperature</h2><span class="zone z-cold" id="cargoState" style="background:var(--good-soft);color:var(--good)">In range</span></div>
        <div class="eta-line"><span class="v num" id="cargoV">${cargo[cargo.length - 1].toFixed(1)}</span><span class="leg-sub">°C · safe range 2–8 °C</span></div>
        <div id="spark">${sparkSVG(cargo)}</div><p class="leg-sub">Cold-chain sensor, last 12 readings (sample data).</p></section>
    </div>
    <section class="card s6"><div class="card-h"><h2>Shipment timeline</h2><small>S204 · Pharma cold-chain, 40 kg</small></div>
      <ul class="timeline">
        <li class="done"><i></i><b>Origin · picked up at Pune hub</b><span>09:10</span></li>
        <li class="done"><i></i><b>Scanned at Nagpur sorting centre</b><span>15:40</span></li>
        <li class="done"><i></i><b>Flagged as misplaced</b><span>16:20 · not loaded on the Kolkata truck</span></li>
        <li class="done"><i></i><b>Recovery booked</b><span>16:45 · ${best.via}</span></li>
        <li class="now"><i></i><b>Current · <span id="tlPlace">in transit</span></b><span id="tlSub">Live position updates every few seconds</span></li>
        <li><i></i><b>Destination · Kolkata hub</b><span>ETA <span id="etaTl">${fmtT(best.h)}</span></span></li></ul></section>
    <section class="card s6"><div class="card-h"><h2>Expedite shipment</h2><small>willing to pay up to</small></div>
      <div class="eta-line"><span class="v num" id="prem">₹0</span><span class="leg-sub">extra</span></div>
      <label class="sr" for="premR" style="position:absolute;left:-9999px">Extra amount you are willing to pay</label>
      <input class="big-range" id="premR" type="range" min="0" max="2400" step="100" value="0">
      <p class="leg-sub" style="margin:6px 0 16px">Your amount feeds the bounty ceiling. It doesn't override the router: MAARG still picks the fastest plan your amount can buy.</p>
      <div class="plan-cols" style="grid-template-columns:repeat(2,1fr)"><div><small>Revised arrival</small><b class="num" id="etaB" style="font-size:20px"></b></div><div><small>Plan</small><b id="stratB" style="font-size:15px;line-height:1.3"></b></div></div>
      <div id="optList"></div><button class="btn" style="margin-top:14px;justify-content:center;width:100%" id="payBtn">Confirm expedite</button></section>
  </div>`;
  shell(root, "customer", "Track my shipment", "Live status, temperature and a way to speed things up.", `<span class="pill"><span class="dot live"></span>Live</span>`, body, { icon: "pin", navLabel: "My shipment" });

  /* expedite */
  function paintExpedite() {
    const P = +$("#premR").value; $("#prem").textContent = inr(P);
    const base = best.c + best.hand;
    const ok = p.opts.filter(o => (o.c + o.hand) - base <= P).sort((a, b) => a.h - b.h)[0];
    $("#etaB").textContent = fmtT(ok.h); $("#stratB").textContent = ok.strat.replace("_", "-") + " · " + ok.via;
    ["#etaTop", "#etaTl", "#etaDest"].forEach(q => $(q).textContent = fmtT(ok.h));
    $("#optList").innerHTML = `<p class="explain-h">Options at this amount</p>` + p.opts.slice().sort((a, b) => a.h - b.h).map(o => { const extra = (o.c + o.hand) - base, un = extra <= P; return `<div class="alt" style="grid-template-columns:auto 1fr auto;${un ? "" : "opacity:.5"}"><span class="strat ${o.strat}">${o.strat.replace("_", "-")}</span><span style="font-size:13.5px">${fmtT(o.h)}</span><span class="num" style="font-size:13px">${o === best ? "engine pick" : extra > 0 ? "+" + inr(extra) : "−" + inr(-extra)}</span></div>`; }).join("");
  }
  $("#premR").addEventListener("input", paintExpedite); paintExpedite();
  $("#payBtn").addEventListener("click", () => { const P = +$("#premR").value, a = Bounty.expedite(s.id, P); toast(a ? `Expedite of ${inr(P)} sent. MaxBounty on ${a.id} is now ${inr(a.maxB)}, so faster vehicles can bid.` : "Expedite request sent. It feeds the bounty ceiling of the next auction for this shipment."); });

  /* live map + simulated progress */
  createLiveMap($("#liveMap")).then(ctl => {
    const nagFrac = ctl.route.frac([21.1458, 79.0882]);
    let t = nagFrac + .36 * (1 - nagFrac);
    const hasKey = !!(window.MAARG_CONFIG && MAARG_CONFIG.GOOGLE_MAPS_API_KEY);
    let shown = "";
    const paintSrc = () => {
      const k = ctl.source + "|" + ctl.roadBy; if (k === shown) return; shown = k;
      $("#mapSrc").innerHTML = ctl.source === "google" ? `<span class="dot"></span>Google Maps · live` : `<span class="dot" style="background:var(--warm)"></span>Leaflet · live`;
      const road = ctl.roadBy === "google" ? "Road route from the Google Directions API. " : ctl.roadBy === "osrm" ? "Road route from OSRM. " : "";
      const why = ctl.source === "google" ? "" : hasKey ? "Google Maps couldn't load with this API key (check that the Maps JavaScript API is enabled, billing is on and the key allows this site), so Leaflet is shown. " : "";
      $("#mapNote").textContent = why + road + "Truck position is simulated along the route; in production it comes from /live_positions/{vehicle_id}.";
    };
    paintSrc(); ctl.roadReady.then(paintSrc);
    const tick = () => {
      paintSrc();
      const pos = ctl.update(t, s.id), pl = nearestPlace(pos), pct = Math.round(t * 100), left = Math.round((1 - t) * ctl.route.total);
      $("#curPlace").textContent = "Near " + pl.name; $("#tlPlace").textContent = "near " + pl.name;
      const sub = "Moving · " + left.toLocaleString("en-IN") + " km to Kolkata"; $("#curSub").textContent = sub; $("#tlSub").textContent = sub;
      $("#railFill").style.width = pct + "%"; $("#railBar").setAttribute("aria-valuenow", pct); $("#pctDone").textContent = pct + "% covered"; $("#kmLeft").textContent = left.toLocaleString("en-IN") + " km to go";
      t = Math.min(.995, t + .0022);
      /* cargo sensor */
      cargo.push(clamp(3.6, 6.2, cargo[cargo.length - 1] + (Math.random() - .5) * .5)); cargo.shift();
      const v = cargo[cargo.length - 1]; $("#cargoV").textContent = v.toFixed(1); $("#spark").innerHTML = sparkSVG(cargo);
      const ok = v >= 2 && v <= 8; const cs = $("#cargoState"); cs.textContent = ok ? "In range" : "Out of range"; cs.style.background = ok ? "var(--good-soft)" : "var(--hot-soft)"; cs.style.color = ok ? "var(--good)" : "var(--hot)";
    };
    tick(); const iv = setInterval(tick, 2500); onLeave(() => clearInterval(iv));
  });
}
