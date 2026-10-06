/* Shared helpers: DOM, toast, theme, nav, footer, portal shell */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
let _leave = [];
const onLeave = fn => _leave.push(fn);
function runLeave() { _leave.forEach(f => { try { f(); } catch (e) { } }); _leave = []; }
const fmtCd = s => String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
const pad2 = n => String(n).padStart(2, "0");

/* light (cream) is the default theme; the toggle switches to dark */
(function bootTheme() { let t = "light"; try { t = localStorage.getItem("maarg-theme") || "light"; } catch (e) { } document.documentElement.dataset.theme = t; })();

function toast(msg) {
  let h = $(".toast-host");
  if (!h) { h = document.createElement("div"); h.className = "toast-host"; h.setAttribute("role", "status"); document.body.appendChild(h); }
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; h.appendChild(t);
  setTimeout(() => t.remove(), 3600);
}
const themeIcon = () => (document.documentElement.dataset.theme === "dark" ? ic("sun") : ic("moon"));
function wireTheme(root) {
  $$("[data-theme-toggle]", root).forEach(b => b.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("maarg-theme", next); } catch (e) { }
    $$("[data-theme-toggle]").forEach(x => x.innerHTML = themeIcon());
    document.dispatchEvent(new Event("themechange"));
  }));
  $$("[data-signout]", root).forEach(b => b.addEventListener("click", () => { Session.clear(); if (typeof MAARG !== "undefined") MAARG.signOut(); location.href = "index.html"; }));
}

function navHTML() {
  const acc = Session.account(), mine = acc ? acc.page : "login.html";
  return `<header class="nav">
    <a class="logo" href="index.html" aria-label="MAARG home">${LOGO}<span>MAARG</span></a>
    <nav class="nav-links" id="navLinks" aria-label="Primary">
      <a href="index.html#engines">Engines</a><a href="index.html#roles">Roles</a><a href="architecture.html">Architecture</a><a href="${mine}">${acc ? "My portal" : "Sign in"}</a>
    </nav>
    <div class="nav-cta">
      ${acc ? `<span class="pill nav-who">${ic("user").replace("<svg", '<svg width="14" height="14"')}${acc.label}</span>` : ""}
      <button class="theme-btn" data-theme-toggle aria-label="Toggle light and dark theme">${themeIcon()}</button>
      ${acc ? `<button class="btn sm ghost" data-signout>Sign out</button>` : `<a class="btn sm" href="login.html">Sign in</a>`}
      <button class="theme-btn menu-btn" id="menuBtn" aria-label="Open menu" aria-expanded="false">${ic("menu")}</button>
    </div>
  </header>`;
}
function wireNav(root) {
  const mb = $("#menuBtn", root), nl = $("#navLinks", root);
  if (mb) mb.addEventListener("click", () => { const o = nl.classList.toggle("open"); mb.setAttribute("aria-expanded", o); });
  wireTheme(root);
}
function footHTML() {
  return `<footer class="foot wrap">
    <div><a class="logo" href="index.html">${LOGO}<span>MAARG</span></a><p style="margin-top:12px;max-width:36ch">MAARG means “path”. It predicts where cargo goes missing and brings it home on vehicles already heading that way.</p></div>
    <div class="cols">
      <div><h4>Explore</h4><a href="index.html#engines">Engines</a><a href="index.html#how">How it works</a><a href="index.html#roles">Four roles</a><a href="index.html#heat">Risk heat map</a><a href="architecture.html">Architecture</a></div>
      <div><h4>Sign in as</h4><a href="login.html?role=admin">Admin</a><a href="login.html?role=dispatcher">Dispatcher</a><a href="login.html?role=driver">Driver</a><a href="login.html?role=customer">Customer</a></div>
      <div><h4>Quick reference</h4><span>Urgency: λ = SLA penalty × (1 + T ÷ 50)</span><br><span>Bounty: pay = min(2nd-lowest bid, MaxBounty)</span><br><span>Ceiling: MaxBounty = min(λ × Δt, C_ded − C_overhead)</span></div>
    </div></footer>`;
}

function pageHead(title, sub, tools) {
  return `<div class="page-head"><div><h1>${title}</h1><p>${sub || ""}</p></div><div class="head-tools">${tools || ""}</div></div>`;
}

/* Portal shell. The sidebar only ever shows the signed-in role's own sections. */
function shell(root, role, title, sub, tools, body, opts = {}) {
  const acc = ACCOUNTS[role];
  const views = opts.views || [];
  root.innerHTML = `<div class="shell">
    <aside class="side">
      <a class="logo" href="index.html">${LOGO}<span>MAARG</span></a>
      <div class="grp"><p class="grp-t">${acc.label} portal</p><nav aria-label="${acc.label} sections">${views.length
        ? views.map(v => `<button type="button" data-view="${v[0]}" class="${v[0] === opts.active ? "on" : ""}">${ic(v[2])}${v[1]}</button>`).join("")
        : `<a class="on" aria-current="page" href="${acc.page}">${ic(opts.icon || ({ admin: "chart", dispatcher: "list", driver: "truck", customer: "pin" })[role])}${opts.navLabel || title}</a>`}</nav></div>
      <div class="grp"><p class="grp-t">MAARG</p><nav aria-label="Platform"><a href="index.html">${ic("home")}Home</a><button type="button" data-signout>${ic("out")}Sign out</button></nav></div>
      <div class="me"><span class="avatar">${acc.name[0]}</span><div><b>${acc.name}</b><small>${acc.who}</small></div><button class="theme-btn" style="margin-left:auto;width:32px;height:32px" data-theme-toggle aria-label="Toggle light and dark theme">${themeIcon()}</button></div>
    </aside>
    <main class="main">${opts.noHead ? "" : pageHead(title, sub, tools)}${body}</main></div>`;
  wireTheme(root);
}
