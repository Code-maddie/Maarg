/* SVG chart helpers */
/* ---------- charts ---------- */
function lineChart(a, b) {
  const W = 520, H = 230, L = 40, R = 56, T = 16, B = 30, x = h => L + (h / 20) * (W - L - R), y = v => T + (100 - v) / 24 * (H - T - B);
  const pathOf = s => s.map((p, i) => (i ? "L" : "M") + x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1)).join(" ");
  const last = s => s[s.length - 1];
  const grid = [76, 80, 85, 90, 95, 100].map(v => `<line class="grid-l" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("");
  const xt = [0, 5, 10, 15, 20].map(h => `<text x="${x(h)}" y="${H - 8}" text-anchor="middle">${h}h</text>`).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="On-time delivery over 20 simulated hours: MAARG rises to 96.4 percent, baseline falls to 81.7 percent">
    ${grid}${xt}
    <path d="${pathOf(a)} L${x(20)} ${y(76)} L${x(0)} ${y(76)}Z" fill="var(--accent)" opacity=".12"/>
    <path d="${pathOf(b)}" fill="none" stroke="var(--ink-3)" stroke-width="2" stroke-dasharray="5 4"/>
    <path d="${pathOf(a)}" fill="none" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${x(20)}" cy="${y(last(a)[1])}" r="5" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/><circle cx="${x(20)}" cy="${y(last(b)[1])}" r="4" fill="var(--ink-3)"/>
    <text class="val" x="${x(20) + 10}" y="${y(last(a)[1]) + 4}">${last(a)[1]}%</text><text class="lbl" x="${x(20) + 10}" y="${y(last(b)[1]) + 4}">${last(b)[1]}%</text></svg>`;
}
function barsH(rows, max, fmt) {
  const W = 520, rowH = 46, L = 118, R = 70;
  return `<svg class="chart" viewBox="0 0 ${W} ${rows.length * rowH + 6}" role="img" aria-label="${rows.map(r => r.label + " " + fmt(r.v)).join(", ")}">
    ${rows.map((r, i) => { const w = (r.v / max) * (W - L - R), y = i * rowH + 6; return `<text class="lbl" x="0" y="${y + 21}">${r.label}</text><rect x="${L}" y="${y + 6}" width="${w}" height="24" rx="6" fill="${r.color}"/><text class="val" x="${L + w + 10}" y="${y + 23}">${fmt(r.v)}</text>`; }).join("")}</svg>`;
}
function mixBar(mix) {
  const cols = { PIGGYBACK: "var(--good)", HYBRID: "var(--warm)", DEDICATED: "var(--hot)", PRE_RESERVED: "var(--cold)" };
  let acc = 0;
  const segs = mix.map(([k, v]) => { const s = `<rect x="${acc}" y="0" width="${v * 5.2}" height="34" fill="${cols[k]}"/>`; acc += v * 5.2; return s; }).join("");
  return `<svg class="chart" viewBox="0 0 520 34" style="border-radius:8px;overflow:hidden" role="img" aria-label="${mix.map(m => m[0] + " " + m[1] + " percent").join(", ")}">${segs}</svg>
    <div class="legend-inline" style="margin-top:14px">${mix.map(([k, v]) => `<span><i style="background:${cols[k]}"></i>${k.replace("_", "-").toLowerCase()} <b class="num" style="color:var(--ink)">${v}%</b></span>`).join("")}</div>`;
}
function latencyBars(rows) {
  const max = Math.log10(2101), W = 520;
  return `<svg class="chart" viewBox="0 0 ${W} 150" role="img" aria-label="Re-plan latency: pre-reserved 0 ms, warm start 60 ms, cold 2100 ms, log scale">
    ${rows.map((r, i) => { const w = Math.max(3, Math.log10(r[1] + 1) / max * (W - 210)), y = i * 46 + 6, c = i === 2 ? "var(--hot)" : i === 1 ? "var(--accent)" : "var(--good)"; return `<text class="lbl" x="0" y="${y + 21}">${r[0]}</text><rect x="138" y="${y + 6}" width="${w}" height="24" rx="6" fill="${c}"/><text class="val" x="${138 + w + 10}" y="${y + 23}">${r[1].toLocaleString("en-IN")} ms</text>`; }).join("")}
    <text x="138" y="146">log scale</text></svg>`;
}
function ringSvg(p, size = 74, sw = 9) {
  const r = (size - sw) / 2, c = 2 * Math.PI * r;
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true" style="transform:rotate(-90deg);flex:none"><circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="currentColor" stroke-opacity=".22" stroke-width="${sw}"/><circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-dasharray="${c * p} ${c}"/></svg>`;
}

