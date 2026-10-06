/* Live shipment map (Leaflet). Route: OSRM road route when reachable, otherwise straight legs between the waypoint cities.
   Vehicle position is simulated along the route; in production it comes from /live_positions/{vehicle_id}. */
const ROUTE_WP = [
  ["Pune", 18.5204, 73.8567], ["Aurangabad", 19.8762, 75.3433], ["Akola", 20.7002, 77.0082], ["Nagpur", 21.1458, 79.0882],
  ["Raipur", 21.2514, 81.6296], ["Sambalpur", 21.4669, 83.9812], ["Jamshedpur", 22.8046, 86.2029], ["Kolkata", 22.5726, 88.3639],
];
const hav = (a, b) => {
  const R = 6371, rad = x => x * Math.PI / 180, dLa = rad(b[0] - a[0]), dLo = rad(b[1] - a[1]);
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLo / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
};
/* a route is an array of [lat, lng]; walk along it by fraction of total distance */
function makeRoute(pts) {
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + hav(pts[i - 1], pts[i]));
  const total = cum[cum.length - 1];
  return {
    pts, total,
    at(t) {
      const d = clamp(0, 1, t) * total; let i = 1;
      while (i < cum.length - 1 && cum[i] < d) i++;
      const seg = (cum[i] - cum[i - 1]) || 1, u = (d - cum[i - 1]) / seg;
      return { lat: pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * u, lng: pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * u, i };
    },
    frac(p) { let best = 0, bd = 1e9; pts.forEach((q, i) => { const d = hav(p, q); if (d < bd) { bd = d; best = i; } }); return cum[best] / total; },
  };
}
const nearestPlace = pos => { let n = ROUTE_WP[0], bd = 1e9; ROUTE_WP.forEach(w => { const d = hav([pos.lat, pos.lng], [w[1], w[2]]); if (d < bd) { bd = d; n = w; } }); return { name: n[0], km: bd }; };

/* Road route: Google Directions when Google Maps is active, else OSRM's public server. Resolves { path, by } or null. */
async function fetchRoadRoute() {
  /* first, middle, last: works for the 8 sample cities and for a live 2–3 hub route */
  const wp = [ROUTE_WP[0], ROUTE_WP[Math.floor((ROUTE_WP.length - 1) / 2)], ROUTE_WP[ROUTE_WP.length - 1]];
  if (googleUsable() && google.maps.DirectionsService) {
    const path = await new Promise(res => {
      const t = setTimeout(() => res(null), 6000);
      try {
        new google.maps.DirectionsService().route({
          origin: { lat: wp[0][1], lng: wp[0][2] }, destination: { lat: wp[2][1], lng: wp[2][2] }, waypoints: [{ location: { lat: wp[1][1], lng: wp[1][2] }, stopover: true }],
          travelMode: google.maps.TravelMode.DRIVING,
        }, (r, status) => { clearTimeout(t); res(status === "OK" && r.routes[0] ? r.routes[0].overview_path.map(q => [q.lat(), q.lng()]) : null); });
      } catch (e) { clearTimeout(t); res(null); }
    });
    if (path && path.length > 1) return { path, by: "google" };
  }
  try {
    const ctrl = new AbortController(), to = setTimeout(() => ctrl.abort(), 7000);
    const co = wp.map(w => w[2] + "," + w[1]).join(";");
    const r = await fetch("https://router.project-osrm.org/route/v1/driving/" + co + "?overview=simplified&geometries=geojson", { signal: ctrl.signal });
    clearTimeout(to); const j = await r.json();
    if (j.code === "Ok" && j.routes[0]) return { path: j.routes[0].geometry.coordinates.map(c => [c[1], c[0]]), by: "osrm" };
  } catch (e) { }
  return null;
}

/* Returns { source (live getter), roadBy, route, update(t, label), roadReady: Promise<boolean> } */
async function createLiveMap(el, o = {}) {
  const base = makeRoute(ROUTE_WP.map(w => [w[1], w[2]]));
  const m = createNetworkMap(el, { heat: false, cands: false, legs: false, labels: false, hubs: false, wheel: true });
  const baseMarks = o.marks || (pts => [{ lat: pts[0][0], lng: pts[0][1], color: "var(--ink)", label: "Origin · Pune" }, { lat: pts[pts.length - 1][0], lng: pts[pts.length - 1][1], color: "var(--good)", label: "Destination · Kolkata" }]);
  let extra = [];
  const marks = pts => baseMarks(pts).concat(extra);
  m.setRoutePoints(base.pts, marks(base.pts));
  document.addEventListener("themechange", () => m.redraw());
  const ctl = {
    get source() { return m.kind(); }, roadBy: null, route: base, t: 0,
    setExtra(list) { extra = list; m.setRoutePoints(ctl.route.pts, marks(ctl.route.pts)); ctl.update(ctl.t, ctl.label); },
    update(t, label) {
      ctl.t = t; ctl.label = label; const p = ctl.route.at(t), q = ctl.route.at(Math.min(1, t + .004));
      m.setLive(p.lat, p.lng, label, q.lng >= p.lng ? 1 : -1); return p;
    },
  };
  ctl.roadReady = fetchRoadRoute().then(r => {
    if (!r) return false;
    ctl.roadBy = r.by; ctl.route = makeRoute(r.path); m.setRoutePoints(r.path, marks(r.path)); ctl.update(ctl.t); return true;
  });
  return ctl;
}
