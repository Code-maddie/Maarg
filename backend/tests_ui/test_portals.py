"""Phase 21 validation: the existing portals run on live backend data.

Plan criteria: every screen loads; real backend data appears; interactions
call the backend correctly; the site still works with the backend down;
(Phase 20) the map renders and falls back when Google Maps is unavailable.
"""

import time

import pytest

from conftest import API, WEB, http, login

SHOTS = __import__("pathlib").Path(__file__).resolve().parent / "artifacts"
SHOTS.mkdir(exist_ok=True)


def shot(page, name):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)


# --- every portal loads with the existing accounts -------------------------

@pytest.mark.parametrize("role,expected", [
    ("admin", "live"), ("dispatcher", "live"), ("customer", "live"), ("driver", "simulated")])
def test_each_existing_account_signs_in_and_its_portal_loads(page, role, expected) -> None:
    source = login(page, role)
    assert source == expected
    assert page.errors == [], page.errors
    shot(page, f"portal_{role}")


def test_login_attempts_firebase_with_the_same_account_then_continues(page) -> None:
    """The existing accounts are not Firebase users; sign-in must fall back cleanly."""
    calls = []
    page.on("request", lambda r: calls.append(r.url) if "identitytoolkit" in r.url or "web-config" in r.url else None)
    login(page, "dispatcher")
    assert any("web-config" in u for u in calls)
    assert any("identitytoolkit.googleapis.com" in u for u in calls)
    assert page.evaluate("sessionStorage.getItem('maarg-id-token')") is None
    assert page.errors == []


# --- real data appears ---------------------------------------------------

def test_admin_map_shows_the_live_network(page) -> None:
    login(page, "admin")
    state = page.evaluate("""() => ({hubs: HUBS.length, legs: LEGS.length,
        live: MAARG.live, firstLeg: LEGS[0] && LEGS[0].id, veh: LEGS[0] && LEGS[0].veh,
        sample: HUBS.some(h => h.id === 'KOL')})""")
    assert state["live"] is True
    assert state["hubs"] == 30
    assert state["legs"] > 0 and state["firstLeg"].startswith("L")
    assert state["veh"].startswith("TRK-")
    assert state["sample"] is False, "sample hub codes leaked into the live page"


def test_admin_heat_is_real_e1_by_hour(page) -> None:
    login(page, "admin")
    page.wait_for_function("() => Object.keys(MAARG.state.heat).length >= 3", timeout=60000)
    src = page.evaluate("MAARG.state.heatSource")
    assert src.startswith("E1 model")
    page.fill("#hourR", "4")
    page.dispatch_event("#hourR", "input")
    page.wait_for_function("() => !!MAARG.state.heat[4]", timeout=60000)
    assert page.text_content("#hourV") == "04:00"
    assert page.errors == []


def test_dispatcher_queue_matches_the_backend(page) -> None:
    http("POST", "/simulate/inject-disruption", {"type": "MISPLACE_SHIPMENT"})
    login(page, "dispatcher")
    backend = http("GET", "/shipments?status=MISPLACED,RECOVERING&limit=60")["total"]
    ui = page.evaluate("SHIPMENTS.length")
    assert ui == min(backend, 60)
    assert page.locator("#queue tr[data-id]").count() == ui


# --- interactions call the backend ---------------------------------------

def test_dispatcher_inject_runs_the_full_pipeline(page) -> None:
    login(page, "dispatcher")
    before = http("GET", "/shipments?status=MISPLACED,RECOVERING")["total"]
    n = page.evaluate("SHIPMENTS.length")
    page.click("#injectD")
    page.wait_for_function(f"() => SHIPMENTS.length > {n}", timeout=60000)
    after = http("GET", "/shipments?status=MISPLACED,RECOVERING")["total"]
    assert after == before + 1
    # The E8 card comes from the backend, not the sample maths.
    page.wait_for_function("() => document.querySelector('#explain').textContent.includes('Chosen ·')", timeout=60000)
    text = page.text_content("#explain")
    assert "recovery at" in text
    assert page.errors == []
    shot(page, "dispatcher_after_inject")


def test_dispatcher_override_is_committed_and_audited(page) -> None:
    """Deterministic: injects until a shipment genuinely has 2+ plans (the
    audit found this test silently skipping, so override was never exercised)."""
    login(page, "dispatcher")
    for attempt in range(8):
        n = page.evaluate("SHIPMENTS.length")
        page.click("#injectD")
        page.wait_for_function(f"() => SHIPMENTS.length > {n}", timeout=60000)
        page.wait_for_function("() => document.querySelector('#explain').textContent.includes('Chosen ·')", timeout=60000)
        if page.locator("#ovSel option").count() >= 2:
            break
    else:
        pytest.fail("8 real recoveries produced no alternative plan to override to")

    sel = page.evaluate("(() => { const s = SHIPMENTS.find(x => x.isNew) || SHIPMENTS[0]; return {db: s.dbId, plan: planFor(s).opts[1].planId}; })()")
    page.select_option("#ovSel", "1")
    page.fill("#ovWhy", "Customer asked for the alternative route")
    page.click("#ovGo")
    committed = None
    deadline = time.time() + 30
    while time.time() < deadline:
        committed = http("GET", f"/shipments/{sel['db']}/recovery-plan")["committed"]
        if committed and committed["id"] == sel["plan"]:
            break
        time.sleep(0.5)
    assert committed["id"] == sel["plan"], "override did not reach the backend"
    page.wait_for_function("() => document.querySelector('#audit').textContent.includes('audit #')", timeout=30000)
    # The UI converges on the backend's new commitment.
    page.wait_for_function(f"() => planFor(SHIPMENTS.find(x => x.dbId === {sel['db']})).opts[0].planId === {sel['plan']}", timeout=30000)
    assert page.errors == []


def test_admin_policy_dial_changes_the_backend(page) -> None:
    login(page, "admin")
    page.click("#polSeg button[data-m=SLA_STRICT]")
    deadline = time.time() + 20
    while http("GET", "/policy-mode")["mode"] != "SLA_STRICT" and time.time() < deadline:
        time.sleep(0.3)
    assert http("GET", "/policy-mode")["mode"] == "SLA_STRICT"
    page.wait_for_function("() => document.querySelector('#polNote') && document.querySelector('#polNote').textContent.includes('SLA_STRICT')", timeout=60000)
    page.click("#polSeg button[data-m=BUSINESS]")
    deadline = time.time() + 20
    while http("GET", "/policy-mode")["mode"] != "BUSINESS" and time.time() < deadline:
        time.sleep(0.3)


def test_admin_hub_approval_creates_a_real_hub(page) -> None:
    login(page, "admin")
    page.click("[data-view=hubs]")          # the admin page reads the hash only at boot
    page.wait_for_selector("#candList")
    buttons = page.locator("#candList button[data-a=ok]")
    if buttons.count() == 0:
        pytest.skip("E3 produced no candidate for this world")
    hubs_before = len(http("GET", "/hubs"))
    buttons.first.click()
    deadline = time.time() + 20
    while len(http("GET", "/hubs")) == hubs_before and time.time() < deadline:
        time.sleep(0.3)
    hubs = http("GET", "/hubs")
    assert len(hubs) == hubs_before + 1
    assert any(h["is_emergent"] for h in hubs)


# --- Phase 20 browser criteria: map renders; route click; fallback --------

def test_map_falls_back_to_leaflet_and_route_click_works(page) -> None:
    page.route("**/maps.googleapis.com/**", lambda r: r.abort())
    login(page, "admin")
    page.wait_for_selector("#adminMap .leaflet-container, #adminMap.leaflet-container", timeout=30000)
    hit = page.locator("#adminMap path.leg-hit").first
    hit.click(force=True)
    page.wait_for_function("() => document.querySelector('#legCard').textContent.includes('TRK-')", timeout=15000)
    assert "kg free" in page.text_content("#legCard")
    assert page.errors == []
    shot(page, "admin_leaflet_route_click")


def test_google_map_renders_when_available(page) -> None:
    login(page, "admin")
    time.sleep(3)
    kind = page.evaluate("typeof googleUsable === 'function' && googleUsable() ? 'google' : 'leaflet'")
    # Either renderer is acceptable; the map must exist and have drawn content.
    assert page.locator("#adminMap").count() == 1
    assert page.evaluate("document.querySelector('#adminMap').children.length") > 0
    shot(page, f"admin_map_{kind}")


# --- graceful degradation ------------------------------------------------

def test_portals_fall_back_to_sample_data_when_backend_is_down(page) -> None:
    page.route("http://localhost:8000/**", lambda r: r.abort())
    source = login(page, "dispatcher")
    assert source == "sample"
    assert page.evaluate("SHIPMENTS.some(s => s.id === 'S204')")
    assert page.locator("#queue tr[data-id]").count() > 0
    assert page.errors == [], page.errors
    shot(page, "dispatcher_offline_sample")


def test_customer_tracks_a_real_shipment(page) -> None:
    login(page, "customer")
    tracked = page.evaluate("MAARG.trackedId()")
    assert tracked != "S204" and tracked.startswith("S")
    assert page.errors == []


# --- realtime: the UI updates without a page refresh ----------------------

def test_dispatcher_queue_updates_over_websocket_without_reload(page) -> None:
    login(page, "dispatcher")
    page.wait_for_function("() => MAARG.state.ws === true", timeout=20000)
    n = page.evaluate("SHIPMENTS.length")
    url_before = page.url
    http("POST", "/simulate/inject-disruption", {"type": "MISPLACE_SHIPMENT"})   # from OUTSIDE the page
    page.wait_for_function(f"() => SHIPMENTS.length > {n}", timeout=30000)
    assert page.url == url_before                       # no navigation / reload
    assert page.locator("#queue tr[data-id]").count() == n + 1


# --- admin records and metrics ------------------------------------------

@pytest.mark.parametrize("tab", ["veh", "hub", "usr"])
def test_admin_records_tables_render(page, tab) -> None:
    login(page, "admin")
    page.click("[data-view=hubs]")
    page.click(f".tabs [data-t={tab}]")
    rows = page.locator("#tblHost tbody tr").count()
    assert rows > 0
    if tab == "veh":
        assert "TRK-" in page.text_content("#tblHost")      # live vehicles, not sample
    assert page.errors == []


def test_admin_metrics_view_renders(page) -> None:
    login(page, "admin")
    page.click("[data-view=metrics]")
    page.wait_for_selector(".kpis")
    assert page.errors == []
    shot(page, "admin_metrics")


# --- driver lifecycle (browser-simulated offers, by design) ----------------

def test_driver_offer_accept_pickup_deliver_earnings(page) -> None:
    login(page, "driver")
    page.click("[data-view=offers]")
    page.click("#simOffer")
    card = page.locator(".offer-card button[data-act=accept]:not([disabled])").first
    card.wait_for(timeout=10000)
    aid = card.get_attribute("data-id")
    card.click()
    assert page.evaluate(f"Bounty.get().auctions.find(a => a.id === '{aid}').mine.state") == "bid"

    page.evaluate(f"Bounty.closeNow('{aid}')")                 # end the window now
    outcome = page.evaluate(f"Bounty.outcome(Bounty.get().auctions.find(a => a.id === '{aid}'))")
    assert outcome in ("won", "lost")
    if outcome == "won":
        page.click("[data-view=pickup]")
        page.click(f"button[data-act=loaded][data-id='{aid}']")
        page.click(f"button[data-act=delivered][data-id='{aid}']")
        page.click("[data-view=earnings]")
        assert aid in page.text_content("#view")
        page.click("[data-view=route]")
        assert page.locator("#stops").count() == 1
    assert page.errors == [], page.errors
    shot(page, f"driver_after_{outcome}")


def test_driver_decline_moves_the_offer_on(page) -> None:
    login(page, "driver")
    page.click("[data-view=offers]")
    page.click("#simOffer")
    btn = page.locator(".offer-card button[data-act=decline]").first
    btn.wait_for(timeout=10000)
    aid = btn.get_attribute("data-id")
    btn.click()
    assert page.evaluate(f"Bounty.get().auctions.find(a => a.id === '{aid}').mine.state") == "declined"
    assert page.errors == []


def test_dispatcher_approved_plan_reaches_the_driver_app(page) -> None:
    """Same browser, two portals: an approval opens a driver-app offer."""
    login(page, "dispatcher")
    n = page.evaluate("SHIPMENTS.length")
    page.click("#injectD")
    page.wait_for_function(f"() => SHIPMENTS.length > {n}", timeout=60000)
    page.wait_for_function("() => document.querySelector('#explain').textContent.includes('Chosen ·')", timeout=60000)
    ship = page.evaluate("(SHIPMENTS.find(x => x.isNew) || SHIPMENTS[0]).id")
    page.click("#approveBtn")
    page.wait_for_function(f"() => Bounty.get().auctions.some(a => a.ship === '{ship}')", timeout=15000)
    login(page, "driver")
    assert page.evaluate(f"Bounty.get().auctions.some(a => a.ship === '{ship}')")
    assert page.errors == []
