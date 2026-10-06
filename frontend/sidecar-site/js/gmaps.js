/* Google Maps implementation of the MAARG network map (same features as the Leaflet one) and the
   createNetworkMap() wrapper: uses Google Maps when it loaded, otherwise (or if Google rejects the key) Leaflet. */
const GM_LIGHT = [
  { elementType: "geometry", stylers: [{ color: "#f3e8d2" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#5f513f" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#f7f0e3" }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#c9b692" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#e6d5b2" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#dcbd8f" }] },
  { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#c9a878" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#cfe0dc" }] },
];
const GM_DARK = [
  { elementType: "geometry", stylers: [{ color: "#2f251a" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#c2b29a" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#1d1711" }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#5b4a35" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#4a3c2c" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#1f2f33" }] },
];
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const googleUsable = () => !!(window.google && google.maps && google.maps.Map) && !(window.MAARG_GM && MAARG_GM.failed);

let _gmk = null;
function gmClasses() {
  if (_gmk) return _gmk;
  /* an HTML element pinned to a lat/lng (used for hubs, pins, labels and the moving trucks) */
  class HtmlMarker extends google.maps.OverlayView {
    constructor(map, lat, lng, html, cls, onClick, title) {
      super(); this.ll = new google.maps.LatLng(lat, lng);
      this.d = document.createElement("div"); this.d.className = "gm-mk " + cls; this.d.innerHTML = html; if (title) this.d.title = title;
      if (onClick) {
        this.d.tabIndex = 0; this.d.setAttribute("role", "button"); this.d.classList.add("clickable");
        this.d.addEventListener("click", e => { e.stopPropagation(); onClick(); });
        this.d.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } });
      }
      this.setMap(map);
    }
    /* Google can call onAdd after the map is torn down (fast view switch): getPanes() is then undefined */
    onAdd() { const panes = this.getPanes(); if (panes) panes.overlayMouseTarget.appendChild(this.d); }
    draw() { const p = this.getProjection(); if (!p) return; const px = p.fromLatLngToDivPixel(this.ll); if (px) { this.d.style.left = px.x + "px"; this.d.style.top = px.y + "px"; } }
    onRemove() { this.d.remove(); }
    move(lat, lng) { this.ll = new google.maps.LatLng(lat, lng); this.draw(); }
    flip(f) { this.d.classList.toggle("flip", f); }
  }
  /* canvas heat overlay in the base map pane, repainted on every pan/zoom */
  class HeatOverlay extends google.maps.OverlayView {
    constructor(map) { super(); this.pts = []; this.vis = true; this.sh = document.createElement("canvas"); this.setMap(map); }
    onAdd() { const panes = this.getPanes(); if (!panes) return; this.c = document.createElement("canvas"); this.c.className = "maarg-heat"; this.c.style.position = "absolute"; panes.mapPane.appendChild(this.c); }
    onRemove() { if (this.c) this.c.remove(); }
    update(pts, vis) { if (pts) this.pts = pts; if (vis !== undefined) this.vis = vis; this.draw(); }
    draw() {
      const proj = this.getProjection(), map = this.getMap(); if (!proj || !this.c || !map) return;
      const div = map.getDiv(), W = div.clientWidth, H = div.clientHeight; if (!W || !H) return;
      const tl = proj.fromContainerPixelToLatLng(new google.maps.Point(0, 0)); const o = tl && proj.fromLatLngToDivPixel(tl); if (!o) return;
      this.c.style.left = o.x + "px"; this.c.style.top = o.y + "px"; this.c.width = this.sh.width = W; this.c.height = this.sh.height = H;
      if (!this.vis) return;
      paintHeat(this.c, this.sh, this.pts, (la, ln) => proj.fromLatLngToContainerPixel(new google.maps.LatLng(la, ln)) || { x: -9999, y: -9999 }, map.getZoom());
    }
  }
  return (_gmk = { HtmlMarker, HeatOverlay });
}

function createGoogleMap(el, o) {
  const { HtmlMarker, HeatOverlay } = gmClasses();
  el.classList.add("netmap", "gm-host"); el.innerHTML = "";
  const map = new google.maps.Map(el, {
    center: { lat: 22, lng: 81 }, zoom: 5, minZoom: 4, maxZoom: 16, disableDefaultUI: true, zoomControl: true,
    zoomControlOptions: { position: google.maps.ControlPosition.RIGHT_TOP }, gestureHandling: o.wheel ? "greedy" : "cooperative",
    clickableIcons: false, keyboardShortcuts: false, backgroundColor: "#f3e8d2", styles: themeName() === "dark" ? GM_DARK : GM_LIGHT,
  });
  /* Google maps use whole zoom levels: level 5 fits the hub network when the map is big enough, otherwise level 4 */
  const fitAll = () => map.setOptions({ center: { lat: 20.6, lng: 82 }, zoom: el.clientHeight >= 560 && el.clientWidth >= 520 ? 5 : 4 });
  fitAll(); let routeFitted = false;

  const heat = new HeatOverlay(map); heat.update(heatPoints(o.hour), o.heat);
  google.maps.event.addListener(map, "idle", () => heat.draw());
  const cols = () => ({ ink: cssv("--ink"), ink2: cssv("--ink-2"), accent: cssv("--accent"), surface: cssv("--surface-hi") });

  let selected = null, lines = {}, dots = [], iv = null, legObjs = [], hubObjs = [], candObjs = [], routeObjs = [], live = null, tip = null;
  const clear = arr => { arr.forEach(x => x.setMap(null)); arr.length = 0; };
  const lineStyle = (l, sel) => { const c = cols(); return sel ? { strokeColor: c.ink, strokeOpacity: 1, strokeWeight: 4 } : l.auction ? { strokeColor: c.accent, strokeOpacity: 1, strokeWeight: 3 } : { strokeColor: c.ink2, strokeOpacity: .68, strokeWeight: 2 }; };

  function drawLegs() {
    clear(legObjs); lines = {}; dots = []; clearInterval(iv);
    if (!o.legs) return;
    LEGS.forEach((l, idx) => {
      const pts = legPoints(l), path = pts.map(p => ({ lat: p[0], lng: p[1] })), pick = () => { setSelected(l.id); o.onLeg && o.onLeg(l); };
      const dash = l.auction ? { icons: [{ icon: { path: "M 0,-1 0,1", strokeOpacity: 1, scale: 2.4 }, offset: "0", repeat: "12px" }] } : {};
      const ln = new google.maps.Polyline({ map, path, clickable: false, geodesic: false, ...lineStyle(l, false), ...(l.auction ? { strokeOpacity: 0, ...dash } : {}) });
      const hit = new google.maps.Polyline({ map, path, strokeOpacity: 0.001, strokeWeight: 16, zIndex: 5 });
      hit.addListener("click", pick);
      hit.addListener("mouseover", e => { if (tip) tip.setMap(null); tip = new HtmlMarker(map, e.latLng.lat(), e.latLng.lng(), `<span>${l.veh} · ${hub(l.from).name} → ${hub(l.to).name}</span>`, "leg-tip-gm"); });
      hit.addListener("mouseout", () => { if (tip) { tip.setMap(null); tip = null; } });
      lines[l.id] = { ln, l }; legObjs.push(ln, hit);
      const truck = new HtmlMarker(map, pts[0][0], pts[0][1], TRUCK_SVG, "veh-gm", pick, `${l.veh}, ${hub(l.from).name} to ${hub(l.to).name}`);
      legObjs.push(truck); dots.push({ truck, pts, ph: (idx * .137) % 1, sp: .0014 + (l.tot % 7) * .0001 });
      if (REDUCED) { const m = along(pts, .5); truck.move(m[0], m[1]); }
    });
    if (!REDUCED) iv = setInterval(() => {
      if (!el.isConnected) { clearInterval(iv); return; }
      dots.forEach(d => { d.ph = (d.ph + d.sp * 3) % 1; const p = along(d.pts, d.ph), q = along(d.pts, Math.min(1, d.ph + .02)); d.truck.move(p[0], p[1]); d.truck.flip(q[1] < p[1]); });
    }, 90);
    if (selected) setSelected(selected);
  }
  function setSelected(id) {
    selected = id;
    Object.entries(lines).forEach(([k, { ln, l }]) => {
      const st = lineStyle(l, k === id); ln.setOptions(l.auction && k !== id ? { ...st, strokeOpacity: 0 } : st);
      ln.setOptions({ zIndex: k === id ? 4 : 1 });
    });
  }
  function drawHubs() {
    clear(hubObjs); if (!o.hubs) return;
    HUBS.forEach(h => hubObjs.push(new HtmlMarker(map, h.lat, h.lon, `<i></i>${o.labels ? `<span>${h.name}</span>` : ""}`, "hub-gm " + (h.a === "start" ? "r" : h.a === "end" ? "l" : "t"))));
  }
  function drawCands() {
    clear(candObjs); if (!o.cands) return;
    CANDIDATES.filter(c => c.status !== "REJECTED").forEach(c => candObjs.push(new HtmlMarker(map, c.lat, c.lon, CAND_PIN, "cand-gm", null, `${c.name}: hub score ${c.score}`)));
  }
  function setRoutePoints(latlng, marks) {
    clear(routeObjs); const c = cols(), path = latlng.map(p => ({ lat: p[0], lng: p[1] }));
    routeObjs.push(new google.maps.Polyline({ map, path, clickable: false, strokeColor: c.surface, strokeOpacity: .92, strokeWeight: 9, zIndex: 2 }),
      new google.maps.Polyline({ map, path, clickable: false, strokeColor: c.accent, strokeOpacity: 1, strokeWeight: 4, zIndex: 3 }));
    (marks || []).forEach(m => routeObjs.push(new HtmlMarker(map, m.lat, m.lng, m.truck ? truckMark(m.label) : `<i style="--c:${m.color}"></i>${m.label ? `<span>${m.label}</span>` : ""}`, m.truck ? "mk-truck" : "mk")));
    if (o.fitRoute && latlng.length > 1) {
      routeFitted = true; const b = new google.maps.LatLngBounds(); path.forEach(p => b.extend(p)); map.fitBounds(b, 46);
      google.maps.event.addListenerOnce(map, "idle", () => { if (map.getZoom() > 8) map.setZoom(8); });
    }
  }
  function setRoute(codes, marks) {
    if (!codes || codes.length < 2) { clear(routeObjs); return; }
    setRoutePoints(codes.map(c => [hub(c).lat, hub(c).lon]), (marks || []).map(m => ({ lat: hub(m.hub).lat, lng: hub(m.hub).lon, color: m.color, label: m.label, truck: m.truck })));
  }
  function setLive(lat, lng, label, dir) {
    if (!live) live = new HtmlMarker(map, lat, lng, `<b></b>${TRUCK_SVG}${label ? `<span>${label}</span>` : ""}`, "live-dot");
    else live.move(lat, lng);
    live.flip(dir < 0);
  }
  drawLegs(); drawHubs(); drawCands();
  return {
    kind: "google", map, setRoute, setRoutePoints, setLive, select: setSelected,
    setHour(h) { o.hour = h; heat.update(heatPoints(h)); },
    setHeat(v) { o.heat = v; heat.update(null, v); },
    setCands(v) { o.cands = v; drawCands(); },
    redraw() { map.setOptions({ styles: themeName() === "dark" ? GM_DARK : GM_LIGHT }); setSelected(selected); if (routeObjs.length) { /* recolour route */ const c = cols(); routeObjs[0].setOptions({ strokeColor: c.surface }); routeObjs[1].setOptions({ strokeColor: c.accent }); } drawCands(); heat.update(heatPoints(o.hour)); },
    destroy() { clearInterval(iv); google.maps.event.clearInstanceListeners(map); },
  };
}

/* One map API for every page. Google Maps first; Leaflet if Google isn't available or rejects the key. */
function createNetworkMap(el, opts = {}) {
  const o = Object.assign({ hour: 17, heat: true, cands: true, legs: true, labels: true, onLeg: null, wheel: false, fitRoute: true, hubs: true }, opts);
  const st = { route: null, live: null, sel: null };
  let impl = null;
  function build(kind) {
    if (impl && impl.destroy) impl.destroy();
    impl = kind === "google" ? createGoogleMap(el, o) : createLeafletMap(el, o);
    if (st.route) st.route.pts ? impl.setRoutePoints(st.route.pts, st.route.marks) : impl.setRoute(st.route.codes, st.route.marks);
    if (st.live) impl.setLive(...st.live);
    if (st.sel) impl.select(st.sel);
  }
  if (googleUsable()) {
    try { build("google"); MAARG_GM.handlers.push(() => build("leaflet")); } catch (e) { build("leaflet"); }
  } else build("leaflet");
  return {
    kind: () => impl.kind, get map() { return impl.map; },
    setHour: h => impl.setHour(h), setHeat: v => impl.setHeat(v), setCands: v => impl.setCands(v),
    select: id => { st.sel = id; impl.select(id); },
    setRoute: (codes, marks) => { st.route = { codes, marks }; impl.setRoute(codes, marks); },
    setRoutePoints: (pts, marks) => { st.route = { pts, marks }; impl.setRoutePoints(pts, marks); },
    setLive: (...a) => { st.live = a; impl.setLive(...a); },
    redraw: () => impl.redraw(),
  };
}
