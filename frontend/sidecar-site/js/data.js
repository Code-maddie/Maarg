/* MAARG sample data — mirrors the SH-205 build document. All figures are simulation samples. */
const inr = n => "₹" + Math.round(n).toLocaleString("en-IN");
const clamp = (a, b, x) => Math.min(b, Math.max(a, x));

const HUBS = [
  { id: "DEL", name: "Delhi", lon: 77.2, lat: 28.6, base: .62, dx: 9, dy: -8, a: "start" },
  { id: "CHD", name: "Chandigarh", lon: 76.8, lat: 30.7, base: .28, dx: -9, dy: -6, a: "end" },
  { id: "JAI", name: "Jaipur", lon: 75.8, lat: 26.9, base: .4, dx: -9, dy: 4, a: "end" },
  { id: "LKO", name: "Lucknow", lon: 80.9, lat: 26.8, base: .46, dx: 9, dy: -4, a: "start" },
  { id: "PAT", name: "Patna", lon: 85.1, lat: 25.6, base: .5, dx: 9, dy: -5, a: "start" },
  { id: "GAU", name: "Guwahati", lon: 91.7, lat: 26.1, base: .3, dx: 0, dy: -11, a: "middle" },
  { id: "KOL", name: "Kolkata", lon: 88.4, lat: 22.6, base: .66, dx: 9, dy: 4, a: "start" },
  { id: "BBI", name: "Bhubaneswar", lon: 85.8, lat: 20.3, base: .34, dx: 10, dy: 4, a: "start" },
  { id: "AMD", name: "Ahmedabad", lon: 72.6, lat: 23.0, base: .52, dx: -9, dy: -4, a: "end" },
  { id: "SUR", name: "Surat", lon: 72.8, lat: 21.2, base: .44, dx: -9, dy: 4, a: "end" },
  { id: "BPL", name: "Bhopal", lon: 77.4, lat: 23.3, base: .38, dx: 0, dy: -11, a: "middle" },
  { id: "NAG", name: "Nagpur", lon: 79.1, lat: 21.1, base: .58, dx: 9, dy: -4, a: "start" },
  { id: "BOM", name: "Mumbai", lon: 72.9, lat: 19.1, base: .78, dx: -9, dy: 4, a: "end" },
  { id: "PNQ", name: "Pune", lon: 73.9, lat: 18.5, base: .6, dx: 9, dy: 10, a: "start" },
  { id: "HYD", name: "Hyderabad", lon: 78.5, lat: 17.4, base: .55, dx: -9, dy: 4, a: "end" },
  { id: "BLR", name: "Bengaluru", lon: 77.6, lat: 13.0, base: .42, dx: -9, dy: 4, a: "end" },
  { id: "MAA", name: "Chennai", lon: 80.3, lat: 13.1, base: .5, dx: 9, dy: 4, a: "start" },
  { id: "COK", name: "Kochi", lon: 76.3, lat: 10.0, base: .26, dx: -9, dy: 8, a: "end" },
];
const hub = id => HUBS.find(h => h.id === id);

const INDIA = [[77.8,35.5],[79.5,33.0],[78.8,31.0],[80.2,30.2],[81.0,30.1],[80.1,28.8],[82.0,27.7],[84.5,27.3],[88.1,26.5],[88.0,27.5],[88.8,27.2],[92.0,27.8],[94.5,29.2],[96.0,28.3],[97.3,28.0],[96.0,27.2],[95.2,26.0],[94.6,24.5],[93.4,23.0],[93.0,22.2],[92.3,23.7],[91.5,24.1],[91.0,25.2],[89.8,25.3],[89.0,26.2],[88.9,25.3],[89.0,24.0],[88.6,22.8],[88.0,21.6],[87.0,21.5],[86.5,20.2],[85.0,19.3],[83.0,17.3],[82.3,16.5],[80.3,15.5],[80.1,13.4],[79.8,11.6],[79.3,10.3],[78.2,8.9],[77.5,8.1],[76.5,9.0],[75.5,11.5],[74.6,13.4],[73.6,16.0],[72.8,19.0],[72.8,21.0],[72.6,22.3],[72.0,21.2],[70.5,20.8],[69.0,22.3],[70.2,22.9],[68.5,23.4],[68.2,23.6],[70.0,24.2],[70.5,25.7],[70.3,27.8],[72.8,29.0],[74.0,30.5],[74.5,31.5],[74.8,32.5],[74.3,34.8],[76.0,35.8]];

const MAP_W = 620, MAP_H = 600;
const proj = (lon, lat) => [(lon - 67.5) * 19.5, (37.4 - lat) * 19.5];
const hubXY = id => { const h = hub(id); return proj(h.lon, h.lat); };

/* Leg = one vehicle movement between two hubs */
const LEGS = [
  { id: "L01", veh: "Truck 12", type: "Owned", from: "PNQ", to: "NAG", dep: "17:10", arr: "01:40", tot: 500, res: 85, rel: .93, aboard: [["S204", 45, 100], ["S311", 17, 60]], auction: null },
  { id: "L02", veh: "Truck 31", type: "Third-party", from: "BOM", to: "AMD", dep: "16:30", arr: "23:10", tot: 800, res: 240, rel: .88, aboard: [["S118", 22, 70]], auction: null },
  { id: "L03", veh: "Truck 07", type: "Owned", from: "AMD", to: "DEL", dep: "18:00", arr: "07:30", tot: 900, res: 310, rel: .95, aboard: [["S402", 30, 90], ["S077", 12, 50]], auction: null },
  { id: "L04", veh: "Van 4", type: "Third-party", from: "HYD", to: "BLR", dep: "17:45", arr: "02:15", tot: 300, res: 120, rel: .81, aboard: [["S231", 62, 110]], auction: { closes: 118, best: 360 } },
  { id: "L05", veh: "Truck 19", type: "Owned", from: "NAG", to: "KOL", dep: "15:20", arr: "09:50", tot: 700, res: 60, rel: .9, aboard: [["S066", 71, 120], ["S190", 38, 80], ["S303", 9, 40]], auction: null },
  { id: "L06", veh: "Truck 25", type: "Owned", from: "DEL", to: "LKO", dep: "19:00", arr: "02:20", tot: 650, res: 205, rel: .92, aboard: [["S388", 26, 75]], auction: null },
  { id: "L07", veh: "Truck 03", type: "Third-party", from: "LKO", to: "PAT", dep: "20:10", arr: "03:30", tot: 600, res: 170, rel: .84, aboard: [], auction: null },
  { id: "L08", veh: "Truck 28", type: "Owned", from: "KOL", to: "GAU", dep: "14:00", arr: "06:45", tot: 750, res: 390, rel: .87, aboard: [["S144", 19, 65]], auction: null },
  { id: "L09", veh: "Van 9", type: "Owned", from: "BLR", to: "MAA", dep: "18:25", arr: "23:40", tot: 350, res: 55, rel: .96, aboard: [["S250", 34, 85], ["S261", 14, 45]], auction: null },
  { id: "L10", veh: "Truck 16", type: "Third-party", from: "BLR", to: "COK", dep: "17:00", arr: "01:10", tot: 550, res: 260, rel: .79, aboard: [], auction: null },
  { id: "L11", veh: "Truck 22", type: "Owned", from: "BPL", to: "NAG", dep: "16:40", arr: "22:15", tot: 620, res: 140, rel: .91, aboard: [["S099", 40, 95]], auction: null },
  { id: "L12", veh: "Truck 08", type: "Owned", from: "JAI", to: "DEL", dep: "18:30", arr: "23:50", tot: 700, res: 275, rel: .94, aboard: [], auction: null },
  { id: "L13", veh: "Truck 33", type: "Third-party", from: "SUR", to: "PNQ", dep: "17:20", arr: "23:00", tot: 480, res: 190, rel: .86, aboard: [["S412", 20, 60]], auction: null },
  { id: "L14", veh: "Truck 14", type: "Owned", from: "HYD", to: "NAG", dep: "19:15", arr: "03:45", tot: 640, res: 95, rel: .89, aboard: [["S275", 55, 100]], auction: null },
  { id: "L15", veh: "Van 2", type: "Owned", from: "DEL", to: "CHD", dep: "17:50", arr: "22:10", tot: 320, res: 150, rel: .93, aboard: [], auction: null },
  { id: "L16", veh: "Truck 05", type: "Third-party", from: "KOL", to: "BBI", dep: "16:10", arr: "22:40", tot: 580, res: 210, rel: .85, aboard: [["S330", 27, 70]], auction: null },
  { id: "L17", veh: "Truck 12", type: "Owned", from: "NAG", to: "KOL", dep: "02:10", arr: "17:40", tot: 500, res: 85, rel: .93, aboard: [], auction: { closes: 255, best: 560 } },
];
const leg = id => LEGS.find(l => l.id === id);

/* Risk model: P(misplace) per hub × hour  (E1 Foresight output, sample) */
const gauss = (x, m, s) => Math.exp(-((x - m) ** 2) / (2 * s * s));
function riskAt(h, hour) {
  const t = hour + 0.0;
  const f = .22 + .55 * gauss(t, 9, 2.4) + .85 * gauss(t, 17.5, 2.8) + .2 * gauss(t, 23.5, 2) + .2 * gauss(t, -0.5, 2);
  return clamp(0, 1, h.base * f * 1.15);
}
function heatPoints(hour) {
  const pts = [];
  HUBS.forEach(h => pts.push({ lat: h.lat, lng: h.lon, w: riskAt(h, hour), km: 210 }));
  LEGS.forEach(l => {
    const a = hub(l.from), b = hub(l.to), ra = riskAt(a, hour), rb = riskAt(b, hour);
    [.33, .66].forEach(t => pts.push({ lat: a.lat + (b.lat - a.lat) * t, lng: a.lon + (b.lon - a.lon) * t, w: (ra * (1 - t) + rb * t) * .55, km: 140 }));
  });
  return pts;
}

/* Hub emergence candidates (E3) */
const CANDIDATES = [
  { id: "C1", name: "Nashik bypass", lon: 73.8, lat: 20.0, usage: 412, risk: .61, cost: 38, save: 74, status: "PENDING" },
  { id: "C2", name: "Raipur ring road", lon: 81.6, lat: 21.25, usage: 336, risk: .54, cost: 42, save: 61, status: "PENDING" },
  { id: "C3", name: "Vijayawada NH-16", lon: 80.65, lat: 16.5, usage: 289, risk: .47, cost: 35, save: 43, status: "PENDING" },
  { id: "C4", name: "Jhansi junction", lon: 78.55, lat: 25.45, usage: 251, risk: .58, cost: 31, save: 47, status: "PENDING" },
];
CANDIDATES.forEach(c => c.score = Math.round(c.usage * c.risk));

/* Policy modes (E4 coefficient re-weighting) */
const POLICIES = {
  BUSINESS: { label: "Business", w: { base: 1.0, time: 1.0, delay: 1.0, cascade: 1.0 }, rec: { strat: "PIGGYBACK", via: "Truck 12 · Pune → Nagpur", cost: 480, eta: "01:40", note: "Balanced cost and speed. Uses spare capacity on an existing run." } },
  SLA_STRICT: { label: "SLA-strict", w: { base: 1.2, time: 1.5, delay: 1.7, cascade: 1.8 }, rec: { strat: "DEDICATED", via: "New truck from Pune hub", cost: 2900, eta: "22:50", note: "Every hour late is penalised hard, so a dedicated vehicle wins." } },
  FAIRNESS: { label: "Fairness", w: { base: .9, time: 1.0, delay: 1.1, cascade: .8 }, rec: { strat: "HYBRID", via: "Truck 12 to Bhopal, then Truck 22", cost: 690, eta: "00:50", note: "Spreads work across drivers instead of loading one vehicle." } },
  EFFICIENCY: { label: "Efficiency", w: { base: .8, time: .6, delay: .7, cascade: .9 }, rec: { strat: "PIGGYBACK", via: "Truck 12 · Pune → Nagpur (next day)", cost: 310, eta: "Tomorrow 09:20", note: "Lowest cost and vehicle-km, accepts a later arrival." } },
};

/* Shipments in the misplaced queue (E4 temperature, λ = sla × (1 + T/50)) */
let SHIPMENTS = [
  { id: "S204", cargo: "Pharma cold-chain, 40 kg", from: "PNQ", at: "NAG", to: "KOL", sla: 100, T: 45, delay: 3.5 },
  { id: "S311", cargo: "Textile rolls, 210 kg", from: "SUR", at: "PNQ", to: "BLR", sla: 60, T: 17, delay: 1.0 },
  { id: "S412", cargo: "Auto parts, 380 kg", from: "AMD", at: "BPL", to: "LKO", sla: 90, T: 72, delay: 5.0 },
  { id: "S118", cargo: "Retail electronics, 95 kg", from: "BOM", at: "AMD", to: "DEL", sla: 120, T: 58, delay: 2.5 },
  { id: "S066", cargo: "Perishables, 150 kg", from: "NAG", at: "BBI", to: "KOL", sla: 140, T: 81, delay: 6.5, cascade: [22, 81] },
  { id: "S231", cargo: "Books & stationery, 120 kg", from: "HYD", at: "BLR", to: "COK", sla: 50, T: 12, delay: .5 },
  { id: "S388", cargo: "Medical devices, 60 kg", from: "DEL", at: "LKO", to: "GAU", sla: 160, T: 66, delay: 4.0 },
  { id: "S250", cargo: "Handloom, 75 kg", from: "BLR", at: "MAA", to: "HYD", sla: 55, T: 29, delay: 1.5 },
  { id: "S263", cargo: "Handloom saris, 62 kg", from: "PNQ", at: "NAG", to: "KOL", sla: 60, T: 30, delay: 1.2 },
  { id: "S271", cargo: "Steel fasteners, 120 kg", from: "AMD", at: "NAG", to: "KOL", sla: 80, T: 52, delay: 2.5 },
  { id: "S144", cargo: "Tea chests, 260 kg", from: "KOL", at: "PAT", to: "DEL", sla: 70, T: 38, delay: 2.0 },
];
const lambda = s => s.sla * (1 + s.T / 50);
const zoneOf = T => T >= 67 ? ["Hot", "z-hot"] : T >= 34 ? ["Warming", "z-warm"] : ["Cold", "z-cold"];

/* k-best recovery options for a shipment */
function planFor(s) {
  const lam = lambda(s);
  const base = 260 + (s.T * 3);
  const opts = [
    { strat: "PIGGYBACK", via: "Truck 12 · " + hub(s.at).name + " → " + hub(s.to).name, c: 420 + s.sla * .6, h: 9.5, hand: 40 },
    { strat: "PRE_RESERVED", via: "Foresight option · Truck 07 slot", c: 610 + s.sla * .7, h: 6, hand: 20 },
    { strat: "HYBRID", via: "Van 4 to hub, then Truck 19", c: 690 + s.sla * .5, h: 7.4, hand: 95 },
    { strat: "DEDICATED", via: "New truck from " + hub(s.at).name + " hub", c: 1500 + s.sla * 3, h: 3.6, hand: 0 },
    { strat: "PIGGYBACK", via: "Truck 31 · " + hub(s.at).name + " → " + hub(s.to).name + " (later)", c: 350 + s.sla * .4, h: 14, hand: 60 },
  ].map(o => ({ ...o, w: o.c + lam * o.h + o.hand }));
  opts.sort((a, b) => a.w - b.w);
  return { lam, opts, base };
}

/* Auction (E5) — Vickrey: winner pays second-lowest bid, capped at MaxBounty */
const BIDDERS = [
  { name: "Truck 12", note: "Owned · 85 kg free", bid: 480 },
  { name: "Truck 31", note: "Third-party · 240 kg free", bid: 560 },
  { name: "Van 4", note: "Third-party · 120 kg free", bid: 620 },
  { name: "Truck 19", note: "Owned · 60 kg free", bid: 710 },
];

/* Vehicles & users tables */
const VEHICLES = LEGS.slice(0, 10).map(l => ({ id: l.veh, type: l.type, route: hub(l.from).name + " → " + hub(l.to).name, tot: l.tot, res: l.res, rel: l.rel }));
const USERS = [
  { name: "Anita Verma", email: "anita@maarg.demo", role: "ADMIN", seen: "Just now" },
  { name: "Rahul Nair", email: "rahul@maarg.demo", role: "DISPATCHER", seen: "2 min ago" },
  { name: "Imran Sheikh", email: "imran@maarg.demo", role: "DISPATCHER", seen: "14 min ago" },
  { name: "Suresh Patil", email: "suresh@maarg.demo", role: "DRIVER", seen: "Truck 12" },
  { name: "Meera Iyer", email: "meera@maarg.demo", role: "CUSTOMER", seen: "Yesterday" },
];

/* Metrics sample */
const METRICS = {
  sla: [[0, 88], [2, 90], [4, 91], [6, 93], [8, 94], [10, 95], [12, 95.5], [14, 96], [16, 96.2], [18, 96.4], [20, 96.4]],
  slaBase: [[0, 88], [2, 86], [4, 85], [6, 84], [8, 83.5], [10, 83], [12, 82.6], [14, 82.2], [16, 82], [18, 81.8], [20, 81.7]],
  cost: { sidecar: 412, base: 587 },
  mix: [["PIGGYBACK", 78], ["HYBRID", 12], ["DEDICATED", 6], ["PRE_RESERVED", 4]],
  latency: [["Pre-reserved", 0], ["Warm-start re-plan", 60], ["Cold re-plan", 2100]],
};

/* Demo script (doc §15) */
const DEMO = [
  ["0–10 s", "Admin logs in; Network Map shows the live risk heatmap", "Admin dashboard", "/admin"],
  ["10–20 s", "Foresight quietly buys an option and a toast confirms it", "Admin dashboard", "/admin"],
  ["20–35 s", "Inject a disruption: the shipment lands in the queue in the Cold zone and an auction starts", "Dispatcher console", "/dispatcher"],
  ["35–65 s", "Cascade: λ jumps 22 → 81 and the plan flips to dedicated. The Explainer shows why", "Explainer panel", "/dispatcher"],
  ["65–80 s", "Foresight payoff: the option is exercised instantly (0 ms vs 60 ms vs 2100 ms)", "Dispatcher console", "/dispatcher"],
  ["80–90 s", "A truck is delayed; warm-start re-plan with a visible latency timer", "Admin dashboard", "/admin"],
  ["90–100 s", "Click a route on the map: vehicle, capacity and bounty status appear", "Network map", "/admin"],
  ["100–110 s", "Switch Policy Mode live and the recommended plan changes", "Admin dashboard", "/admin"],
  ["110–120 s", "Metrics: SLA %, cost, premium burn against the baseline", "Metrics panel", "/admin"],
];

/* extra shipments that can turn up as new offers on Truck 12's corridor (used by "Simulate new offer") */
const DRIVER_POOL = [
  { id: "S281", cargo: "Medical consumables, 48 kg", from: "PNQ", at: "NAG", to: "KOL", sla: 110, T: 44, delay: 2.0 },
  { id: "S284", cargo: "Spare bearings, 30 kg", from: "AMD", at: "NAG", to: "KOL", sla: 70, T: 27, delay: 1.0 },
  { id: "S290", cargo: "Garments, 70 kg", from: "SUR", at: "NAG", to: "KOL", sla: 65, T: 61, delay: 3.0 },
];
