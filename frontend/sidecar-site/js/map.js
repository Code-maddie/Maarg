/* MAARG maps, built on Leaflet.
   Base tiles: Esri World Street Map (light) / Esri Dark Gray canvas (dark). No API key needed.
   Overlays: a custom canvas heat layer, clickable vehicle legs, hub markers, gold hub-candidate pins,
   a highlighted route and a pulsing live-vehicle marker. */
const HEAT_STOPS = [[0, [233, 217, 181, 0]], [.2, [233, 205, 140, 120]], [.45, [217, 160, 80, 190]], [.72, [184, 96, 56, 225]], [1, [123, 45, 38, 245]]];
const HEAT_LUT = (() => {
  const lut = new Uint8ClampedArray(256 * 4);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let a = HEAT_STOPS[0], b = HEAT_STOPS[HEAT_STOPS.length - 1];
    for (let k = 0; k < HEAT_STOPS.length - 1; k++) if (t >= HEAT_STOPS[k][0] && t <= HEAT_STOPS[k + 1][0]) { a = HEAT_STOPS[k]; b = HEAT_STOPS[k + 1]; break; }
    const u = (t - a[0]) / ((b[0] - a[0]) || 1);
    for (let c = 0; c < 4; c++) lut[i * 4 + c] = a[1][c] + (b[1][c] - a[1][c]) * u;
  }
  return lut;
})();

const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
const TILES = {
  light: [ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}"],
  dark: [ESRI + "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", ESRI + "Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"],
};
const TILE_ATTR = 'Tiles &copy; <a href="https://www.esri.com" target="_blank" rel="noopener">Esri</a> &mdash; Esri, HERE, Garmin, FAO, NOAA, USGS, &copy; OpenStreetMap contributors';
const themeName = () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");
const INDIA_BOUNDS = [[7.2, 68.2], [35.8, 97.8]];

/* curved leg between two hubs, sampled as lat/lng points */
function legPoints(l, n = 28) {
  const a = hub(l.from), b = hub(l.to), A = [a.lat, a.lon], B = [b.lat, b.lon];
  const dLat = B[0] - A[0], dLng = B[1] - A[1], k = .13;
  const C = [(A[0] + B[0]) / 2 - dLng * k, (A[1] + B[1]) / 2 + dLat * k], pts = [];
  for (let i = 0; i <= n; i++) { const t = i / n, u = 1 - t; pts.push([u * u * A[0] + 2 * u * t * C[0] + t * t * B[0], u * u * A[1] + 2 * u * t * C[1] + t * t * B[1]]); }
  return pts;
}
const along = (pts, t) => { const f = t * (pts.length - 1), i = Math.min(pts.length - 2, Math.floor(f)), u = f - i; return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u]; };

/* shared heat painter: greyscale alpha blobs colourised through HEAT_LUT. toPx(lat, lng) -> {x, y} in canvas pixels */
function paintHeat(canvas, shadow, pts, toPx, zoom) {
  const W = canvas.width, H = canvas.height, ctx = canvas.getContext("2d"), sctx = shadow.getContext("2d", { willReadFrequently: true });
  ctx.clearRect(0, 0, W, H); if (!W || !H) return;
  sctx.clearRect(0, 0, W, H);
  pts.forEach(p => {
    const pt = toPx(p.lat, p.lng), mpp = 156543.03392 * Math.cos(p.lat * Math.PI / 180) / Math.pow(2, zoom), r = Math.max(8, p.km * 1000 / mpp);
    if (pt.x < -r || pt.y < -r || pt.x > W + r || pt.y > H + r) return;
    const g = sctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, r);
    g.addColorStop(0, `rgba(0,0,0,${clamp(0, 1, p.w).toFixed(3)})`); g.addColorStop(1, "rgba(0,0,0,0)");
    sctx.fillStyle = g; sctx.fillRect(pt.x - r, pt.y - r, r * 2, r * 2);
  });
  const img = sctx.getImageData(0, 0, W, H), d = img.data;
  for (let i = 0; i < d.length; i += 4) { const a = d[i + 3]; if (!a) continue; const k = a * 4; d[i] = HEAT_LUT[k]; d[i + 1] = HEAT_LUT[k + 1]; d[i + 2] = HEAT_LUT[k + 2]; d[i + 3] = HEAT_LUT[k + 3]; }
  sctx.putImageData(img, 0, 0); ctx.drawImage(shadow, 0, 0);
}
/* small side-view truck used for every moving vehicle (cab on the right; flipped when heading west) */
const TRUCK_SVG = `<svg class="truck-fig" viewBox="0 0 40 20" width="30" height="15" aria-hidden="true"><rect x="1" y="3" width="26" height="11" rx="2" fill="#F7EEDC" stroke="#8C5A34" stroke-width="1.3"/><path d="M28 6h6.5l4.5 4.6V14H28z" fill="#7B4A36"/><path d="M30 7.6h4l2.6 3H30z" fill="#DCE7E6"/><rect x="0" y="13.6" width="39.5" height="2.2" rx="1.1" fill="#3A2E24"/><circle cx="8" cy="16.6" r="2.7" fill="#2A2018" stroke="#F7EEDC" stroke-width="1"/><circle cx="18" cy="16.6" r="2.7" fill="#2A2018" stroke="#F7EEDC" stroke-width="1"/><circle cx="33" cy="16.6" r="2.7" fill="#2A2018" stroke="#F7EEDC" stroke-width="1"/></svg>`;
const truckMark = label => `<div class="mk-truck-in">${TRUCK_SVG.replace('width="30" height="15"', 'width="36" height="18"')}${label ? `<span>${label}</span>` : ""}</div>`;

/* canvas heat layer: greyscale alpha blobs colourised through HEAT_LUT, re-drawn on every pan/zoom */
const HeatLayer = L.Layer.extend({
  onAdd(map) {
    this._map = map; this._pts = this._pts || []; this._vis = this._vis !== false;
    this._c = L.DomUtil.create("canvas", "maarg-heat leaflet-zoom-hide"); this._sh = document.createElement("canvas");
    map.getPane("heat").appendChild(this._c);
    map.on("moveend zoomend resize", this._reset, this); this._reset();
  },
  onRemove(map) { L.DomUtil.remove(this._c); map.off("moveend zoomend resize", this._reset, this); },
  setData(p) { this._pts = p || []; if (this._map) this._draw(); },
  setVisible(v) { this._vis = v; if (this._map) this._draw(); },
  _reset() {
    const s = this._map.getSize();
    this._c.width = this._sh.width = s.x; this._c.height = this._sh.height = s.y;
    L.DomUtil.setPosition(this._c, this._map.containerPointToLayerPoint([0, 0])); this._draw();
  },
  _draw() {
    const map = this._map; if (!this._c.width) return;
    if (!this._vis) { this._c.getContext("2d").clearRect(0, 0, this._c.width, this._c.height); return; }
    paintHeat(this._c, this._sh, this._pts, (la, ln) => map.latLngToContainerPoint([la, ln]), map.getZoom());
  },
});

const mkIcon = (color, label, cls = "") => L.divIcon({ className: "mk " + cls, iconSize: [0, 0], html: `<i style="--c:${color}"></i>${label ? `<span>${label}</span>` : ""}` });
const CAND_PIN = `<svg viewBox="-13 -33 26 38" width="26" height="38" aria-hidden="true"><circle cx="0" cy="-2" r="11" fill="none" stroke="var(--gold)" stroke-width="1.3" stroke-dasharray="2 3"/><path d="M0 -3 C-7 -13 -7 -28 0 -28 C7 -28 7 -13 0 -3 Z" fill="var(--gold)" stroke="var(--surface-hi)" stroke-width="1.6"/><circle cx="0" cy="-21" r="2.6" fill="var(--surface-hi)"/></svg>`;

function createLeafletMap(el, opts = {}) {
  const o = Object.assign({ hour: 17, heat: true, cands: true, legs: true, labels: true, onLeg: null, wheel: false, fitRoute: true, hubs: true }, opts);
  el.classList.add("netmap"); el.innerHTML = "";
  const map = L.map(el, { zoomSnap: .25, zoomDelta: .5, minZoom: 4, maxZoom: 12, scrollWheelZoom: o.wheel, zoomControl: false, attributionControl: true });
  L.control.zoom({ position: "topright" }).addTo(map);
  map.attributionControl.setPrefix(false);
  map.createPane("land").style.zIndex = 150; map.createPane("heat").style.zIndex = 350;
  /* stylised India shows through if tiles can't load (offline, blocked) */
  L.polygon(INDIA.map(p => [p[1], p[0]]), { pane: "land", className: "land-poly", interactive: false }).addTo(map);

  let theme = themeName(), tiles = [];
  const setTiles = () => {
    tiles.forEach(t => map.removeLayer(t)); theme = themeName();
    tiles = TILES[theme].map((u, i) => L.tileLayer(u, { maxNativeZoom: 18, maxZoom: 19, attribution: i === 0 ? TILE_ATTR : "" }).addTo(map));
  };
  setTiles();
  const fitAll = () => map.fitBounds(INDIA_BOUNDS, { padding: [6, 6] });
  fitAll(); requestAnimationFrame(() => { map.invalidateSize(); if (!routeFitted) fitAll(); });
  let routeFitted = false;

  const heat = new HeatLayer().addTo(map); heat.setVisible(o.heat); heat.setData(heatPoints(o.hour));

  const gLegs = L.layerGroup().addTo(map), gRoute = L.layerGroup().addTo(map), gHubs = L.layerGroup().addTo(map), gCand = L.layerGroup().addTo(map), gLive = L.layerGroup().addTo(map);
  let selected = null, lines = {}, dots = [], iv = null;

  function drawLegs() {
    gLegs.clearLayers(); lines = {}; dots = []; clearInterval(iv);
    if (!o.legs) return;
    LEGS.forEach((l, idx) => {
      const pts = legPoints(l), pick = () => { setSelected(l.id); o.onLeg && o.onLeg(l); };
      const hit = L.polyline(pts, { weight: 16, opacity: 0, className: "leg-hit", bubblingMouseEvents: false }).addTo(gLegs);
      hit.bindTooltip(`${l.veh} · ${hub(l.from).name} → ${hub(l.to).name}`, { sticky: true, className: "leg-tip" }); hit.on("click", pick);
      lines[l.id] = L.polyline(pts, { weight: 2, className: "leg-line" + (l.auction ? " auction" : ""), interactive: false, lineCap: "round" }).addTo(gLegs);
      const dot = L.marker(pts[0], { icon: L.divIcon({ className: "veh-dot", iconSize: [30, 15], html: TRUCK_SVG }), keyboard: true, title: `${l.veh}, ${hub(l.from).name} to ${hub(l.to).name}`, riseOnHover: true }).addTo(gLegs);
      dot.on("click", pick); dots.push({ dot, pts, ph: (idx * .137) % 1, sp: .0014 + (l.tot % 7) * .0001 });
      if (REDUCED) dot.setLatLng(along(pts, .5));
    });
    if (!REDUCED) iv = setInterval(() => {
      if (!el.isConnected) { clearInterval(iv); map.remove(); return; }
      dots.forEach(d => {
        d.ph = (d.ph + d.sp * 3) % 1; const p = along(d.pts, d.ph), q = along(d.pts, Math.min(1, d.ph + .02));
        d.dot.setLatLng(p); const e = d.dot.getElement(); if (e) e.classList.toggle("flip", q[1] < p[1]);
      });
    }, 90);
    if (selected) setSelected(selected);
  }
  function setSelected(id) {
    selected = id;
    Object.entries(lines).forEach(([k, ln]) => { const e = ln.getElement(); if (e) e.classList.toggle("sel", k === id); if (k === id) ln.bringToFront(); });
  }
  function drawHubs() {
    gHubs.clearLayers(); if (!o.hubs) return;
    HUBS.forEach(h => {
      const m = L.circleMarker([h.lat, h.lon], { radius: 6, weight: 2, className: "hub-dot" }).addTo(gHubs);
      if (o.labels) m.bindTooltip(h.name, { permanent: true, direction: h.a === "start" ? "right" : h.a === "end" ? "left" : "top", offset: [h.a === "start" ? 4 : h.a === "end" ? -4 : 0, h.dy > 5 ? 8 : h.dy < -8 ? -2 : 0], className: "hub-label", opacity: 1 });
    });
  }
  function drawCands() {
    gCand.clearLayers(); if (!o.cands) return;
    CANDIDATES.filter(c => c.status !== "REJECTED").forEach(c => {
      L.marker([c.lat, c.lon], { icon: L.divIcon({ className: "cand-pin", iconSize: [26, 38], iconAnchor: [13, 33], html: CAND_PIN }), title: `${c.name}: hub score ${c.score}`, keyboard: false }).addTo(gCand);
    });
  }

  function setRoutePoints(latlng, marks) {
    gRoute.clearLayers();
    L.polyline(latlng, { className: "route-case", interactive: false, lineCap: "round", lineJoin: "round" }).addTo(gRoute);
    L.polyline(latlng, { className: "route-main", interactive: false, lineCap: "round", lineJoin: "round" }).addTo(gRoute);
    (marks || []).forEach(m => L.marker([m.lat, m.lng], { icon: m.truck ? L.divIcon({ className: "mk-truck", iconSize: [36, 18], html: truckMark(m.label) }) : mkIcon(m.color, m.label), interactive: false, keyboard: false }).addTo(gRoute));
    if (o.fitRoute && latlng.length > 1) { routeFitted = true; map.fitBounds(L.latLngBounds(latlng), { padding: [46, 46], maxZoom: 8 }); }
  }
  function setRoute(codes, marks) {
    if (!codes || codes.length < 2) { gRoute.clearLayers(); return; }
    setRoutePoints(codes.map(c => [hub(c).lat, hub(c).lon]), (marks || []).map(m => ({ lat: hub(m.hub).lat, lng: hub(m.hub).lon, color: m.color, label: m.label, truck: m.truck })));
  }
  let live = null;
  function setLive(lat, lng, label, dir) {
    if (!live) live = L.marker([lat, lng], { icon: L.divIcon({ className: "live-dot", iconSize: [0, 0], html: `<b></b>${TRUCK_SVG}${label ? `<span>${label}</span>` : ""}` }), interactive: false, keyboard: false, zIndexOffset: 1000 }).addTo(gLive);
    else live.setLatLng([lat, lng]);
    const e = live.getElement(); if (e) e.classList.toggle("flip", dir < 0);
  }

  drawLegs(); drawHubs(); drawCands();
  return {
    kind: "leaflet", destroy() { clearInterval(iv); try { map.remove(); } catch (e) { } }, map, setRoute, setRoutePoints, setLive, select: setSelected,
    setHour(h) { o.hour = h; heat.setData(heatPoints(h)); },
    setHeat(v) { o.heat = v; heat.setVisible(v); },
    setCands(v) { o.cands = v; drawCands(); },
    redraw() { if (themeName() !== theme) setTiles(); drawCands(); heat.setData(heatPoints(o.hour)); },
  };
}
