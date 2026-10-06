/* Landing page (shown after sign-in; adapts to the signed-in role) */
const STEPS = [
  ["Predict", "Foresight heat map scores every shipment-leg for misplacement risk before it happens."],
  ["Price", "Temperature turns urgency into one number: λ, the cost of each hour of delay in ₹."],
  ["Plan", "The Piggy Router finds the cheapest recovery on vehicles already heading that way."],
  ["Prove", "The Explainer shows every rejected alternative and why the chosen plan won."],
];
const ENGINES = [
  { ico: "heat", tags: ["E1", "E2"], t: "Foresight heat map & reservation", d: "A classifier scores P(misplace) by hub pair and hour. When risk crosses the critical fractile, Foresight pre-buys cargo space.", roles: ["admin"] },
  { ico: "hub", tags: ["E3"], t: "Hub emergence", d: "Usage frequency × local risk surfaces places that deserve a hub. Admins approve or reject each candidate.", roles: ["admin"] },
  { ico: "therm", tags: ["E4"], t: "Temperature & λ pricing", d: "Every misplaced shipment gets a Cold, Warming or Hot score, then a rupees-per-hour urgency: λ = SLA penalty × (1 + T/50).", roles: ["customer", "dispatcher"] },
  { ico: "gavel", tags: ["E5"], t: "Bounty reverse auction", d: "Vehicles already heading that way bid for the pickup. Vickrey pricing pays the winner the second-lowest bid, capped at MaxBounty.", roles: ["admin", "dispatcher", "driver"], feature: true },
  { ico: "route", tags: ["E6", "E7"], t: "Piggy Router & graph memory", d: "Label-setting search across a time-expanded network. Retained labels warm-start every re-plan, so changes take milliseconds.", roles: ["dispatcher"] },
  { ico: "explain", tags: ["E8"], t: "Counterfactual explainer", d: "Each plan ships with the alternatives it beat and the rupee gap, so every decision has an audit trail.", roles: ["dispatcher"] },
];
const LOOP = [
  { t: "Predict", d: "The heat map had already marked Nagpur's evening handover as a high-risk cell, so the network was watching it before S204 arrived.", f: "E1 scores P(misplace) per hub pair and hour", stat: "High", sub: " risk at 17:00" },
  { t: "Price", d: "S204 is Warming, with temperature 45 (18 base + 12 time + 9 delay + 6 cascade). Every hour of delay now costs a known amount.", f: "λ = 100 × (1 + 45 ÷ 50)", stat: "₹190", sub: " per hour late" },
  { t: "Plan", d: "A bounty auction opens to four vehicles already heading that way. Truck 12 bids its true cost of ₹480 and wins.", f: "MaxBounty = min(190 × 6.5, C_ded − 120) = ₹1,235", stat: "₹560", sub: " paid: second-lowest bid" },
  { t: "Prove", d: "The explainer lists every plan that lost and the rupee gap. A dedicated truck would have cost about ₹2,500. Each approval and override is logged.", f: "Audit trail with a reason for every override", stat: "≈ ₹1,940", sub: " saved vs dedicated" },
];
const ROLE_CARDS = [
  { role: "admin", ico: "chart", need: "Ops head managing the network, policy and analytics.", items: [["Heat map", "with time slider"], ["Metrics dashboard", "SLA, cost, premium burn"], ["Bounty market", "live auctions"], ["Hub emergence", "approve / reject"]] },
  { role: "dispatcher", ico: "list", need: "Ops staff who watch recoveries and approve or override plans.", items: [["Misplaced queue", "hottest first"], ["Recovery plan", "path, cost, ETA"], ["Explainer", "rejected alternatives"], ["Override", "reason logged"]] },
  { role: "driver", ico: "truck", need: "Vehicle operator who answers bounty offers before the timer ends.", items: [["Offer inbox", "countdown ring"], ["Active pickup", "turn-by-turn + QR"], ["My route", "detour shown"], ["Earnings", "bounty ledger"]] },
  { role: "customer", ico: "user", need: "Shipment owner who wants a live ETA and a way to speed things up.", items: [["Shipment timeline", "origin · current · destination"], ["Live map", "Google Maps"], ["Temperature", "urgency + cargo"], ["Expedite", "willing-to-pay ₹X"]] },
];

function home(root) {
  const acc = Session.account(), mine = acc ? acc.page : "login.html";
  root.innerHTML = `
  <div class="wrap home-top">
    <section class="hero" aria-label="MAARG introduction">
      ${heroArt()}
      ${navHTML()}
      <div class="hero-copy"><h1>Misplaced<br>shipments<br>recovered</h1></div>
      <div class="hero-bottom">
        <p>${acc ? `<b style="color:var(--ink)">Welcome back, ${acc.name.split(" ")[0]}.</b> ` : ""}MAARG predicts where cargo goes missing, prices its urgency in rupees per hour, and routes it home on vehicles already heading that way.</p>
        <div class="hero-actions"><a class="btn" href="${mine}">${acc ? `Open ${acc.label.toLowerCase()} portal` : "Sign in"} ${ic("arrow", "arr")}</a><a class="btn ghost" href="#how">How it works</a></div>
      </div>
      <button class="step-card" id="stepCard" aria-label="Next step of the Predict, Price, Plan, Prove loop">
        <div class="thumb" id="stepThumb"></div>
        <div class="body"><div class="row"><h3 id="stepT"></h3><span class="ct"><b id="stepN"></b> / 04</span></div><p id="stepD"></p><div class="bar"><i id="stepBar"></i></div></div>
      </button>
    </section>
    <div class="marquee" aria-label="MAARG features">
      <div class="marquee-track">${[0, 1].map(() => [["heat", "Foresight heat map"], ["clock", "Time-of-day risk slider"], ["therm", "Temperature & λ pricing"], ["gavel", "Bounty reverse auction"], ["route", "Piggy Router"], ["db", "Graph memory"], ["hub", "Hub emergence"], ["explain", "Counterfactual explainer"], ["pin", "Live shipment map"], ["wallet", "Expedite shipment"], ["shield", "Cold-chain monitoring"], ["chart", "Metrics dashboard"], ["truck", "Driver offers"], ["list", "Dispatcher override"]].map(([i, n]) => `<div class="marquee-item">${ic(i)}${n}</div>`).join("")).join("")}</div>
    </div>
  </div>

  <section class="block wrap" id="engines">
    <div class="sec-head"><h2 class="h-light">Our engines</h2><p>Eight engines run one loop. Each role sees the ones it works with; the rest are walked through in the example below.</p></div>
    <div class="svc-grid">${ENGINES.map(e => {
      const mineHas = !!acc && e.roles.includes(acc.role);
      return `<article class="svc${e.feature ? " feature" : ""}">
        <div class="ico">${ic(e.ico)}</div>
        <div class="tags">${e.tags.map(t => `<span class="tag">${t}</span>`).join("")}</div>
        <h3>${e.t}</h3><p>${e.d}</p>
        <a class="btn sm" href="${mineHas ? mine : "#how"}">${mineHas ? "Open in my portal" : "How it works"} ${ic("arrow", "arr")}</a>
      </article>`;
    }).join("")}
    </div>
  </section>

  <section class="block wrap" id="about" style="padding-top:0">
    <div class="about">
      <div class="about-img">${aboutArt()}</div>
      <div class="about-copy">
        <h2 class="h-section">About MAARG</h2>
        <p>MAARG means “path”. It is an intelligent shipment-piggybacking system (SH-205) that predicts where shipments will go missing and pre-buys cargo space against that risk. When a misplacement happens, it prices the shipment's urgency as a rupees-per-hour figure and runs a reverse auction among vehicles already heading that way.</p>
        <p>It then plans the recovery across a time-expanded transport network, re-plans in milliseconds when the network changes, and justifies every rupee with a counterfactual audit trail.</p>
        <div class="formula-strip"><code>T(s) = clamp(0, 100, T_base + T_time + T_delay + T_cascade)</code><code>λ = sla × (1 + T / 50)</code></div>
        <a class="btn" href="#how">See an example ${ic("arrow", "arr")}</a>
      </div>
    </div>
  </section>

  <section class="block wrap" id="roles" style="padding-top:0">
    <div class="sec-head"><h2 class="h-section">Built for four roles</h2><p>Each role has its own sign-in and its own portal.${acc ? ` You are signed in as <b style="color:var(--ink)">${acc.label}</b>.` : ""}</p></div>
    <div class="roles">${ROLE_CARDS.map(r => { const a = ACCOUNTS[r.role], me = !!acc && r.role === acc.role; return `
      <article class="role${me ? " me" : ""}"><div class="ico">${ic(r.ico)}</div><h3>${a.label}${me ? ' <span class="tag">you</span>' : ""}</h3><p class="need">${r.need}</p>
        <ul>${r.items.map(i => `<li>${i[0]}<span>${i[1]}</span></li>`).join("")}</ul>
        ${me ? `<a class="go" href="${a.page}">Open my portal ${ic("arrow", "arr")}</a>` : `<a class="go" href="login.html?role=${r.role}" style="opacity:.75">Sign in as ${a.label} ${ic("arrow", "arr")}</a>`}</article>`; }).join("")}
    </div>
  </section>

  <section class="block wrap" id="heat" style="padding-top:0">
    <div class="heat-sec">
      <div class="card" style="padding:16px">
        <div id="homeMap"></div>
        <div class="map-tools"><div class="slider-row"><label for="homeHour" class="eyebrow">Hour of day</label><input id="homeHour" type="range" min="0" max="23" value="17" aria-label="Hour of day"><span class="hour-badge num" id="homeHourV">17:00</span></div></div>
      </div>
      <div>
        <p class="eyebrow">Foresight heat map · E1</p>
        <h2 class="h-section" style="margin:10px 0 14px">Watch risk shift<br>through the day</h2>
        <p class="lead">Each cell is P(misplace) for a hub pair at an hour. Drag the slider and the peaks move: the morning sorting rush, then the evening handover.</p>
        <div style="margin-top:22px;max-width:420px"><div class="legend-ramp"></div><div class="legend-labels"><span>Low risk</span><span>P(misplace)</span><span>High risk</span></div></div>
        <ul class="point-list">
          <li><span class="pt-ico">${ic("pin")}</span><div><b>Gold pin = proposed hub</b>Where a hot cell meets heavy usage, Hub Emergence suggests a new hub.</div></li>
          <li><span class="pt-ico">${ic("route")}</span><div><b>Every route is a vehicle</b>Dashed routes have a live bounty auction open.</div></li>
        </ul>
      </div>
    </div>
  </section>

  <section class="block wrap" id="how" style="padding-top:0">
    <div class="sec-head"><h2 class="h-section">One shipment, start to finish</h2><p>Shipment S204, 40 kg of pharma cold-chain cargo, is found in Nagpur instead of on its Kolkata truck. This is what MAARG does next.</p></div>
    <div class="loop">${LOOP.map((s, i) => `<article class="step"><div class="step-top"><span class="step-n">0${i + 1}</span><h3>${s.t}</h3></div><p>${s.d}</p><code>${s.f}</code><div class="stat num">${s.stat}<small>${s.sub}</small></div></article>`).join("")}</div>
  </section>

  <section class="wrap" style="padding-bottom:24px">
    <div class="cta-band"><div><h2 class="h-section">Ready when you are</h2><p>${acc ? `Your ${acc.label.toLowerCase()} portal has everything this role needs and nothing it doesn't.` : "Sign in as admin, dispatcher, driver or customer. Each role gets its own portal."}</p></div><a class="btn" href="${mine}">${acc ? `Open ${acc.label.toLowerCase()} portal` : "Sign in"} ${ic("arrow", "arr")}</a></div>
  </section>
  ${footHTML()}`;

  wireNav(root);
  let i = 0, t0 = performance.now(), raf;
  const D = 5200;
  const paint = () => { $("#stepThumb").innerHTML = stepThumb(i); $("#stepT").textContent = STEPS[i][0]; $("#stepN").textContent = "0" + (i + 1); $("#stepD").textContent = STEPS[i][1]; t0 = performance.now(); };
  paint();
  $("#stepCard").addEventListener("click", () => { i = (i + 1) % 4; paint(); });
  const tick = now => { const p = Math.min(1, (now - t0) / D); $("#stepBar").style.width = (p * 100) + "%"; if (p >= 1) { i = (i + 1) % 4; paint(); } raf = requestAnimationFrame(tick); };
  if (!REDUCED) raf = requestAnimationFrame(tick); else $("#stepBar").style.width = "100%";
  const mini = createNetworkMap($("#homeMap"), { hour: 17, legs: true, labels: true });
  $("#homeHour").addEventListener("input", e => { const h = +e.target.value; mini.setHour(h); $("#homeHourV").textContent = pad2(h) + ":00"; });
  document.addEventListener("themechange", () => mini.redraw());
}
