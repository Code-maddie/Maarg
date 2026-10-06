/* Demo accounts + role-gated session.
   Prototype only: credentials are checked in the browser. In production, Firebase Auth issues the role
   as a custom claim and the FastAPI backend re-verifies it on every request. */
const ACCOUNTS = {
  admin: { role: "admin", label: "Admin", name: "Anita Verma", who: "Ops head", email: "anita@maarg.demo", pw: "admin123", page: "admin.html",
    tag: "Network heat map, metrics, bounty market and hub emergence." },
  dispatcher: { role: "dispatcher", label: "Dispatcher", name: "Rahul Nair", who: "Dispatcher", email: "rahul@maarg.demo", pw: "dispatch123", page: "dispatcher.html",
    tag: "Misplaced queue, recovery plans, explainer and overrides." },
  driver: { role: "driver", label: "Driver", name: "Suresh Patil", who: "Truck 12", email: "suresh@maarg.demo", pw: "driver123", page: "driver.html",
    tag: "Your route, bounty offers, active pickup and earnings." },
  customer: { role: "customer", label: "Customer", name: "Meera Iyer", who: "Shipment owner", email: "meera@maarg.demo", pw: "customer123", page: "customer.html",
    tag: "Shipment timeline, live map, temperature and expedite." },
};
const PAGES = { admin: "admin.html", dispatcher: "dispatcher.html", driver: "driver.html", customer: "customer.html" };

const Session = {
  key: "maarg-session",
  get() {
    let raw = null;
    try { raw = localStorage.getItem(this.key); } catch (e) { }
    if (!raw && /^MAARG:/.test(window.name || "")) raw = window.name.slice(6);
    try { const s = JSON.parse(raw); return s && ACCOUNTS[s.role] ? s : null; } catch (e) { return null; }
  },
  set(role) {
    const s = JSON.stringify({ role, at: Date.now() });
    try { localStorage.setItem(this.key, s); } catch (e) { }
    window.name = "MAARG:" + s;
  },
  clear() { try { localStorage.removeItem(this.key); } catch (e) { } window.name = ""; },
  account() { const s = this.get(); return s ? ACCOUNTS[s.role] : null; },
};

/* Returns true when the visitor may see this page. role = null means any signed-in user. */
function guard(role) {
  const s = Session.get();
  if (!s) { location.replace("login.html" + (role ? "?role=" + role + "&needs=1" : "?needs=1")); return false; }
  if (role && s.role !== role) { location.replace("login.html?role=" + role + "&denied=" + s.role); return false; }
  return true;
}
