/* left panel scene: sun, hills, a dotted route and the MAARG truck on the road */
function loginScene() {
  return `<svg class="bg" viewBox="0 0 600 900" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
    <defs>
      <radialGradient id="lgSun" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#FFF6E2" stop-opacity=".95"/><stop offset=".55" stop-color="#FBE6BB" stop-opacity=".5"/><stop offset="1" stop-color="#FBE6BB" stop-opacity="0"/></radialGradient>
      <linearGradient id="lgRoad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6a5440"/><stop offset="1" stop-color="#4b3a2b"/></linearGradient>
    </defs>
    <g fill="none" stroke="var(--hero-ink)" stroke-opacity=".3" stroke-dasharray="2 9" stroke-linecap="round" stroke-width="2"><path d="M430 190 Q585 170 520 335"/></g>
    ${[[430, 190], [520, 335]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="14" fill="none" stroke="var(--hero-ink)" stroke-opacity=".35"/><circle cx="${x}" cy="${y}" r="5" fill="var(--hero-ink)"/>`).join("")}
    <circle cx="430" cy="560" r="230" fill="url(#lgSun)"/><circle cx="430" cy="560" r="70" fill="#FFF3D9" opacity=".85"/>
    <path d="M0 640 Q120 585 250 622 T520 610 T600 620 L600 820 L0 820Z" fill="#D8BC8D" opacity=".8"/>
    <path d="M0 690 Q160 640 320 680 T600 665 L600 840 L0 840Z" fill="#C7A574"/>
    <path d="M0 745 Q220 715 420 742 T600 735 L600 860 L0 860Z" fill="#B48F5F"/>
    <path d="M0 812 L600 788 L600 900 L0 900Z" fill="url(#lgRoad)"/>
    <path d="M0 818 L600 794" stroke="#F3E5C7" stroke-width="4" opacity=".9"/>
    <path d="M0 862 L600 836" stroke="#F3E5C7" stroke-width="4" stroke-dasharray="42 34" opacity=".85"/>
    <g transform="translate(58 596) scale(.86)">${TRUCK("loginTruck")}</g>
  </svg>`;
}

/* Sign-in page: one login per role, each with its own copy and demo credentials */
function login(root) {
  const q = new URLSearchParams(location.search);
  const ORDER = ["admin", "dispatcher", "driver", "customer"];
  let role = ORDER.includes(q.get("role")) ? q.get("role") : "admin";
  const cur = Session.account();
  const HEADS = { admin: ["Run the whole", "network"], dispatcher: ["Recover every", "shipment"], driver: ["Take the", "next offer"], customer: ["Know where", "it is"] };

  root.innerHTML = `<div class="login">
    <div class="login-art">${loginScene()}
      <a class="logo" href="index.html">${LOGO}<span>MAARG</span></a>
      <div style="margin-top:clamp(28px,8vh,88px)"><h2 id="artH"></h2><p style="color:var(--hero-ink-2);max-width:36ch;margin-top:14px" id="artP"></p>
        <small class="art-note" style="display:block;color:var(--hero-ink-2);margin-top:22px;max-width:40ch">MAARG means “path”. Intelligent shipment piggybacking, SH-205 prototype.</small></div>
    </div>
    <div class="login-form">
      <div><p class="eyebrow">Sign in</p><h1 class="h-section" style="margin-top:8px" id="formH"></h1></div>
      <div class="seg" role="tablist" aria-label="Choose your role" id="roleSeg">${ORDER.map(r => `<button type="button" role="tab" data-r="${r}">${ACCOUNTS[r].label}</button>`).join("")}</div>
      <div id="notice"></div>
      <form class="stack" id="lf" novalidate>
        <label class="field">Email<input type="email" id="em" autocomplete="username" required></label>
        <label class="field">Password<input type="password" id="pw" autocomplete="current-password" required></label>
        <p class="form-err" id="err" role="alert"></p>
        <div class="actions"><button class="btn" type="submit">Sign in ${ic("arrow", "arr")}</button></div>
      </form>
      <div class="demo-cred"><div><small class="eyebrow">Demo credentials</small><div class="num" id="credTxt" style="margin-top:4px;font-size:14px"></div></div><button class="btn sm soft" type="button" id="fill">Fill them in</button></div>
      <p class="leg-sub" style="max-width:48ch">Prototype sign-in: accounts are checked in your browser. In production, Firebase Auth issues the role as a custom claim and the API re-verifies it on every request.</p>
    </div></div>`;

  function paint() {
    const a = ACCOUNTS[role];
    $$("#roleSeg button").forEach(b => { const on = b.dataset.r === role; b.classList.toggle("on", on); b.setAttribute("aria-selected", on); });
    $("#formH").textContent = a.label + " sign-in";
    $("#artH").innerHTML = HEADS[role][0] + "<br>" + HEADS[role][1];
    $("#artP").textContent = a.tag;
    $("#credTxt").innerHTML = `${a.email}<br>${a.pw}`;
    $("#err").textContent = "";
    $("#em").value = ""; $("#pw").value = "";
  }
  paint();
  $("#roleSeg").addEventListener("click", e => { const b = e.target.closest("button[data-r]"); if (b) { role = b.dataset.r; paint(); } });
  $("#fill").addEventListener("click", () => { $("#em").value = ACCOUNTS[role].email; $("#pw").value = ACCOUNTS[role].pw; $("#pw").focus(); });

  const n = $("#notice");
  if (q.get("denied") && ACCOUNTS[q.get("denied")]) n.innerHTML = `<div class="banner" style="margin:0">${ic("alert")}<div>That page is for <b>${ACCOUNTS[role].label}</b> accounts. You were signed in as ${ACCOUNTS[q.get("denied")].label}. Sign in with a ${ACCOUNTS[role].label} account to continue.</div></div>`;
  else if (q.get("needs")) n.innerHTML = `<div class="banner" style="margin:0">${ic("alert")}<div>Please sign in to continue.</div></div>`;
  else if (cur) n.innerHTML = `<div class="banner" style="margin:0;background:var(--good-soft)"><div>Signed in as <b>${cur.name}</b> (${cur.label}). <a href="${cur.page}" style="text-decoration:underline">Continue to my portal</a> or sign in below to switch role.</div></div>`;

  $("#lf").addEventListener("submit", e => {
    e.preventDefault();
    const a = ACCOUNTS[role], em = $("#em").value.trim().toLowerCase(), pw = $("#pw").value;
    if (!em || !pw) { $("#err").textContent = "Enter your email and password."; return; }
    if (em !== a.email || pw !== a.pw) { $("#err").textContent = "That email and password don't match a " + a.label + " account. Use “Fill them in” for the demo login."; return; }
    /* Existing demo check passed. Also sign in to the existing Firebase project with the same account so the
       backend receives a verified ID token. If that fails (e.g. the account is not a Firebase user) the demo
       session continues exactly as before. */
    $("#err").textContent = "Signing in…";
    (typeof MAARG !== "undefined" ? MAARG.signIn(em, pw) : Promise.resolve({ ok: false, reason: "api.js not loaded" }))
      .then(r => { if (!r.ok) console.info("Firebase sign-in skipped:", r.reason); })
      .finally(() => { Session.set(role); location.href = a.page; });
  });
}
