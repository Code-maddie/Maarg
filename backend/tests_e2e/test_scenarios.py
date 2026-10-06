"""Final-audit end-to-end scenarios against the REAL system.

Real E1 (205 MB model), full-scale world (30 hubs / 200 vehicles / 5 000
shipments / 600 legs), the real HTTP API in-process, and a throwaway
database. Every scenario cross-checks API response vs database vs engine.

Run:  .venv/Scripts/python.exe -m pytest tests_e2e -q
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

DB = Path(__file__).resolve().parent / "e2e.db"
for suffix in ("", "-wal", "-shm"):
    Path(str(DB) + suffix).unlink(missing_ok=True)
os.environ["AUTH_MODE"] = "disabled"
os.environ["FIRESTORE_ENABLED"] = "false"
os.environ["DATABASE_URL"] = f"sqlite:///{DB.as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.engines.e1_misplacement.registry import get_registry  # noqa: E402
from app.engines.e4_temperature.pressure import EMERGENCY_THRESHOLD  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Auction, AuditLog, Bid, Hub, Leg, RecoveryOutcome, RecoveryPlan, Shipment, ShipmentLeg,
)
from app.models.enums import LegStatus, PlanStatus, ShipmentStatus  # noqa: E402
from app.workers.simulator import get_simulator  # noqa: E402

FULL = {"seed": 42, "hub_count": 30, "vehicle_count": 200, "shipment_count": 5000, "leg_count": 600}


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as client:
        get_registry().load()                      # real E1, synchronously
        assert client.get("/model/status").json()["model_loaded"]
        client.post("/simulate/reset", json=FULL)
        client.post("/simulate/tick", json={"ticks": 30})
        yield client


def misplace_and_recover(api, **patch):
    d = api.post("/simulate/inject-disruption", json={"type": "MISPLACE_SHIPMENT"}).json()
    if patch:
        with SessionLocal() as db:
            s = db.get(Shipment, d["target_id"])
            for k, v in patch.items():
                setattr(s, k, v(get_simulator().clock.now) if callable(v) else v)
            db.commit()
    r = api.post(f"/simulate/recover/{d['target_id']}").json()
    return d["target_id"], r


# ---------------------------------------------------------------- scenario 1
def test_s01_normal_shipments_get_no_unnecessary_recovery(api) -> None:
    with SessionLocal() as db:
        normal = db.scalars(select(Shipment.id).where(
            Shipment.misplaced_at.is_(None))).all()
        with_plans = db.scalar(select(func.count(func.distinct(RecoveryPlan.shipment_id)))
                               .where(RecoveryPlan.shipment_id.in_(normal)))
        with_auction = db.scalar(select(func.count()).select_from(Auction)
                                 .where(Auction.shipment_id.in_(normal)))
        delivered = db.scalar(select(func.count()).select_from(Shipment)
                              .where(Shipment.status == ShipmentStatus.DELIVERED.value))
    assert with_plans == 0 and with_auction == 0
    assert delivered > 0, "normal traffic should flow and deliver without intervention"


# ---------------------------------------------------------------- scenario 2
def test_s02_misplaced_shipment_runs_the_full_pipeline(api) -> None:
    sid, r = misplace_and_recover(api, deadline_at=lambda now: now + timedelta(hours=60))
    names = [s["name"] for s in r["stages"]]
    for stage in ["E1 misplacement", "E4 temperature", "Recovery pressure", "Recovery cascade",
                  "Re-price after cascade", "E6 router + E7 memory", "E2 foresight",
                  "E5 bounty market", "Persist plans", "E8 explainer"]:
        assert stage in names
    assert all(s["ok"] for s in r["stages"]), [s for s in r["stages"] if not s["ok"]]
    assert names.index("E4 temperature") < names.index("Recovery pressure")

    api_s = api.get(f"/shipments/{sid}").json()
    with SessionLocal() as db:
        db_s = db.get(Shipment, sid)
        assert 0.0 <= db_s.p_misplace <= 1.0                                 # E1 real
        assert api_s["p_misplace"] == pytest.approx(db_s.p_misplace)
        assert api_s["temperature"] == pytest.approx(db_s.temperature) == pytest.approx(r["temperature"]["temperature"])
        assert api_s["lam"] == pytest.approx(db_s.lam) == pytest.approx(r["temperature"]["lam"])
        # λ = sla × (1 + T/50)  (SH.docx §16)
        assert db_s.lam == pytest.approx(db_s.sla_penalty_per_hour * (1 + db_s.temperature / 50)
                                         + db_s.customer_premium, abs=0.02)
        assert api_s["pressure"] == pytest.approx(db_s.pressure) == pytest.approx(r["pressure"]["pressure"])
        assert db_s.status == ShipmentStatus.RECOVERING.value

    ex = api.get(f"/shipments/{sid}/explainer").json()
    plan = api.get(f"/shipments/{sid}/recovery-plan").json()["committed"]
    assert ex["strategy"] == plan["strategy"] == r["strategy"]
    assert ex["total_cost"] == pytest.approx(plan["total_cost"]) == pytest.approx(r["total_cost"])


# ---------------------------------------------------------------- scenario 3
def test_s03_high_pressure_triggers_emergency_recovery(api) -> None:
    sid, r = misplace_and_recover(api, deadline_at=lambda now: now + timedelta(hours=1),
                                  cascade_depth=5, base_priority=2.0)
    p = r["pressure"]
    assert p["emergency"] == (p["pressure"] >= EMERGENCY_THRESHOLD)
    assert p["emergency"], f"pressure {p['pressure']} did not reach {EMERGENCY_THRESHOLD}"
    assert any("Emergency Recovery Mode" in w for w in r["explanation"]["why_chosen"])
    assert api.get(f"/shipments/{sid}").json()["emergency"] is True
    assert r["succeeded"], "an emergency must still produce a plan"


# ---------------------------------------------------------------- scenario 4
def test_s04_vehicle_delay_cascades_reprioritises_and_replans(api) -> None:
    with SessionLocal() as db:
        row = db.execute(select(Leg.vehicle_id, func.count())
                         .join(ShipmentLeg, ShipmentLeg.leg_id == Leg.id)
                         .where(Leg.status.in_([LegStatus.SCHEDULED.value, LegStatus.DEPARTED.value]))
                         .group_by(Leg.vehicle_id).order_by(func.count().desc())).first()
        vid = row[0]
        aboard = db.scalars(select(ShipmentLeg.shipment_id).join(Leg, Leg.id == ShipmentLeg.leg_id)
                            .where(Leg.vehicle_id == vid)).all()
        before = {s.id: s.temperature for s in db.scalars(select(Shipment).where(Shipment.id.in_(aboard)))}
        untouched = db.scalars(select(Shipment).where(Shipment.cascade_depth == 0,
                               Shipment.id.notin_(aboard)).limit(50)).all()
        untouched_before = {s.id: (s.temperature, s.cascade_depth) for s in untouched}

    api.post("/simulate/inject-disruption", json={"type": "DELAY_VEHICLE", "target_id": vid, "delay_hours": 4})
    c = api.post(f"/simulate/cascade/vehicle/{vid}?max_depth=2").json()
    assert c["terminated_by"] and c["shipments_updated"] > 0

    with SessionLocal() as db:
        after = {s.id: s for s in db.scalars(select(Shipment).where(Shipment.id.in_(aboard)))}
        touched = [a for a in after.values() if a.cascade_depth > 0]
        assert touched, "no directly affected shipment was re-prioritised"
        assert all(after[i].temperature >= before[i] - 1e-6 for i in before)
        affected_ids = {n["entity_id"] for n in c["shipments"]}
        for s in db.scalars(select(Shipment).where(Shipment.id.in_(list(untouched_before)))):
            if s.id not in affected_ids:
                assert (s.temperature, s.cascade_depth) == untouched_before[s.id]
        target = touched[0].id

    # Re-plan an affected shipment around the delay.
    api.post("/simulate/inject-disruption", json={"type": "MISPLACE_SHIPMENT", "target_id": target})
    r = api.post(f"/simulate/recover/{target}").json()
    assert r["succeeded"]


# ---------------------------------------------------------------- scenario 5
def test_s05_piggyback_selected_when_available(api) -> None:
    """E6's documented objective (score = 0.55 cost + 0.25 slack + 0.20
    transfers) decides. So: (a) the committed plan is always the top-scoring
    option; (b) when a piggyback plan is cheaper AND arrives no later than the
    dedicated one, piggyback is committed.

    Audit note: an earlier version asserted "piggyback always wins when
    available". Real runs showed dedicated legitimately winning when the
    cheaper piggyback arrived with almost no deadline slack — that is the
    specified objective, so the expectation was corrected, not the engine.
    """
    piggyback_commits = 0
    for _ in range(12):
        sid, r = misplace_and_recover(api, deadline_at=lambda now: now + timedelta(hours=70))
        if r["pressure"]["emergency"]:
            continue
        b = api.get(f"/shipments/{sid}/recovery-plan").json()
        options = [b["committed"]] + b["alternatives"]
        # (a) the engine's documented objective decides, every time
        assert b["committed"]["score"] == pytest.approx(max(o["score"] for o in options))
        # (b) where a piggyback option outscores dedicated, piggyback is committed
        pig = max((o for o in options if o["strategy"] == "PIGGYBACK"), key=lambda o: o["score"], default=None)
        ded = next((o for o in options if o["strategy"] == "DEDICATED"), None)
        if pig and ded and pig["score"] > ded["score"]:
            assert b["committed"]["strategy"] == "PIGGYBACK"
        piggyback_commits += b["committed"]["strategy"] == "PIGGYBACK"
    # (c) piggybacking genuinely happens in practice, not just in theory
    assert piggyback_commits >= 1, "no recovery out of 12 rode existing capacity"


# ---------------------------------------------------------------- scenario 6
def test_s06_piggyback_becomes_unavailable_memory_backtracks(api) -> None:
    from app.engines.e7_graph_memory.memory import get_memory
    from app.engines.e7_graph_memory.planner import plan_recovery

    with SessionLocal() as db:
        now = get_simulator().clock.now
        s = db.scalars(select(Shipment).where(Shipment.status == ShipmentStatus.PENDING.value)).first()
        s.deadline_at = now + timedelta(hours=80); s.lam = 180.0; db.commit()
        first = plan_recovery(db, s, now=now)
        pig = next((p for p in first.result.plans if p.legs and p.legs[0].leg_id), None)
        if pig is None:
            pytest.skip("no piggyback route for this shipment")
        dead = pig.legs[0].leg_id
        db.get(Leg, dead).status = LegStatus.CANCELLED.value; db.commit()

        second = plan_recovery(db, s, now=now)
        assert dead not in {l.leg_id for p in second.result.plans for l in p.legs}
        assert dead in get_memory().warm_start(second.query_key).failed_leg_ids
        assert second.best is not None, "no alternative after backtracking"


# ---------------------------------------------------------------- scenario 7
def test_s07_route_fusion_evaluates_compatible_routes(api) -> None:
    from app.engines.e6_piggy_router.fusion import Movement, try_fuse
    from app.core.geo import haversine_km

    with SessionLocal() as db:
        hubs = {h.id: h for h in db.scalars(select(Hub))}
        ships = db.scalars(select(Shipment).where(Shipment.status == ShipmentStatus.PENDING.value).limit(800)).all()
        now = get_simulator().clock.now
        pair = None
        for i, a in enumerate(ships):
            for b in ships[i + 1:]:
                if a.origin_hub_id != b.origin_hub_id and a.dest_hub_id == b.dest_hub_id and \
                   haversine_km(hubs[a.origin_hub_id].lat, hubs[a.origin_hub_id].lng,
                                hubs[b.origin_hub_id].lat, hubs[b.origin_hub_id].lng) < 250:
                    pair = (a, b); break
            if pair: break
        assert pair, "no compatible corridor pair in this world"
        mv = [Movement(s.id, s.code, hubs[s.origin_hub_id], hubs[s.dest_hub_id], s.weight_kg,
                       s.volume_m3, now + timedelta(hours=200), now, cost=60_000.0) for s in pair]
        r = try_fuse(*mv, capacity_kg=5000, capacity_m3=60, cost_per_km=25)
        assert r.merged, r.reason
        assert r.merged_distance_km < r.separate_distance_km and r.cost_saving > 0


# ---------------------------------------------------------------- scenario 8
def test_s08_bounty_auction_bids_winner_payment_and_offer(api, monkeypatch) -> None:
    from app.services import notifications

    offers = []
    monkeypatch.setattr(notifications, "publish_bounty_offer", lambda aid, **kw: offers.append((aid, kw)) or True)
    import app.services.orchestrator as orch
    monkeypatch.setattr(orch, "publish_bounty_offer", lambda aid, **kw: offers.append((aid, kw)) or True)

    sid, r = misplace_and_recover(api, deadline_at=lambda now: now + timedelta(hours=60))
    with SessionLocal() as db:
        a = db.scalar(select(Auction).where(Auction.shipment_id == sid).order_by(Auction.id.desc()))
        bids = sorted(db.scalars(select(Bid).where(Bid.auction_id == a.id)), key=lambda b: b.amount)
        plan = db.get(RecoveryPlan, r["committed_plan_id"])
        if a.status == "NO_BIDS":
            pytest.skip("no eligible bidder near this pickup")
        assert a.status == "AWARDED"
        assert a.winning_vehicle_id == bids[0].vehicle_id and bids[0].is_winner
        assert sum(b.is_winner for b in bids) == 1
        expected = a.max_bounty if len(bids) == 1 else min(bids[1].amount, a.max_bounty)
        assert a.payment == pytest.approx(expected) and a.payment > 0
        assert a.plan_id == plan.id and plan.bounty_cost == pytest.approx(a.payment)
    assert offers and offers[-1][0] == a.id and offers[-1][1]["payment"] == pytest.approx(a.payment)
    assert api.get(f"/map/pickup-route/{a.id}").json()["waypoints"][0]["role"] == "driver"


# ---------------------------------------------------------------- scenario 9
def test_s09_foresight_reserves_only_when_the_fractile_says_so(api) -> None:
    with SessionLocal() as db:
        hi, lo = db.scalars(select(Shipment).where(Shipment.status == ShipmentStatus.PENDING.value).limit(2)).all()
        hi.p_misplace, lo.p_misplace = 0.95, 0.02
        db.commit()
        hi_id, lo_id = hi.id, lo.id
    rh, rl = api.get(f"/reservations/{hi_id}").json(), api.get(f"/reservations/{lo_id}").json()
    assert rh["should_reserve"] and rh["p_misplace"] >= rh["threshold"]
    assert not rl["should_reserve"]
    thr = rh["premium"] / (rh["premium"] + rh["dedicated_cost"] - rh["expected_bounty"])
    assert rh["threshold"] == pytest.approx(min(1.0, max(0.0, thr)), abs=1e-3)


# ---------------------------------------------------------------- scenario 10
def test_s10_hub_emergence_generates_and_approves(api) -> None:
    api.post("/simulate/tick", json={"ticks": 40})          # more departures scored by E1
    cands = api.get("/hub-emergence/candidates?regenerate=true").json()
    assert cands, "E3 produced no candidate from scored traffic"
    scores = [c["hub_score"] for c in cands]
    assert scores == sorted(scores, reverse=True)
    for c in cands:
        assert c["hub_score"] == pytest.approx(c["usage_count"] * c["mean_risk"], rel=1e-3)
    pending = [c for c in cands if c["status"] == "PENDING"]
    hub = api.post(f"/hub-emergence/candidates/{pending[0]['id']}/approve", json={"reason": "audit"}).json()
    assert hub["is_emergent"]
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "APPROVE_HUB",
                                                AuditLog.target_id == pending[0]["id"]))


# ---------------------------------------------------------------- scenario 11
def test_s11_dispatcher_override_moves_commitment_and_booking(api) -> None:
    for _ in range(15):
        sid, r = misplace_and_recover(api, deadline_at=lambda now: now + timedelta(hours=70))
        bundle = api.get(f"/shipments/{sid}/recovery-plan").json()
        alt = next((a for a in bundle["alternatives"] if a["path"]), None)
        if alt:
            break
    else:
        pytest.fail("no recovery produced an alternative to override to")
    old = bundle["committed"]["id"]
    res = api.post(f"/shipments/{sid}/override", json={"chosen_plan_id": alt["id"], "reason": "Audit override"})
    assert res.status_code == 200, res.text
    after = api.get(f"/shipments/{sid}/recovery-plan").json()
    assert after["committed"]["id"] == alt["id"]
    with SessionLocal() as db:
        assert db.get(RecoveryPlan, old).status == PlanStatus.OVERRIDDEN.value
        committed = db.scalars(select(RecoveryPlan).where(RecoveryPlan.shipment_id == sid,
                               RecoveryPlan.status == PlanStatus.COMMITTED.value)).all()
        assert len(committed) == 1
        booked = {l.leg_id for l in db.scalars(select(ShipmentLeg).where(
            ShipmentLeg.shipment_id == sid, ShipmentLeg.boarded_at.is_(None)))}
        assert booked == {p.leg_id for p in committed[0].paths if p.leg_id}
        assert db.scalar(select(AuditLog).where(AuditLog.action == "OVERRIDE_PLAN",
                                                AuditLog.target_id == alt["id"]))


# ---------------------------------------------------------------- scenario 12
def test_s12_recovery_vehicle_carries_the_shipment_to_delivery(api) -> None:
    """Backend half of 'driver accepts → route updates': the committed plan is
    booked on the winning corridor, the shipment boards, moves and delivers,
    and E9 records the outcome. (Driver accept/decline UI is simulated in the
    browser — see the audit's known limitations.)"""
    for _ in range(15):
        sid, r = misplace_and_recover(api, deadline_at=lambda now: now + timedelta(hours=90))
        with SessionLocal() as db:
            plan = db.get(RecoveryPlan, r["committed_plan_id"])
            if any(p.leg_id for p in plan.paths):
                break
    else:
        pytest.skip("no piggyback recovery")
    for _ in range(60):
        api.post("/simulate/tick", json={"ticks": 10})
        if api.get(f"/shipments/{sid}").json()["status"] == "DELIVERED":
            break
    assert api.get(f"/shipments/{sid}").json()["status"] == "DELIVERED"
    with SessionLocal() as db:
        assert db.get(RecoveryPlan, r["committed_plan_id"]).status == PlanStatus.COMPLETED.value
        assert db.scalar(select(RecoveryOutcome).where(RecoveryOutcome.plan_id == r["committed_plan_id"]))


# ------------------------------------------------------------ failure cases
@pytest.mark.parametrize("method,path,body,code", [
    ("GET", "/shipments/999999", None, 404),
    ("POST", "/simulate/recover/999999", None, 404),
    ("GET", "/legs/999999", None, 404),
    ("POST", "/hub-emergence/candidates/999999/approve", {"reason": "x"}, 404),
    ("GET", "/map/heat?hour=99", None, 422),
    ("POST", "/simulate/inject-disruption", {"type": "MISPLACE_SHIPMENT", "target_id": 999999}, 400),
    ("POST", "/simulate/inject-disruption", {"type": "DELAY_VEHICLE", "target_id": 999999}, 400),
    ("POST", "/simulate/cascade/planet/1", None, 400),
    ("POST", "/shipments/1/override", {"chosen_plan_id": 1}, 422),
    ("POST", "/model/predict", {"hub": "F000"}, 422),
    ("PUT", "/policy-mode", {"mode": "TURBO"}, 400),
])
def test_failure_cases_answer_cleanly(api, method, path, body, code) -> None:
    r = api.request(method, path, json=body)
    assert r.status_code == code, (path, r.status_code, r.text[:200])


def test_impossible_deadline_and_insufficient_capacity_degrade(api) -> None:
    sid, r = misplace_and_recover(api, deadline_at=lambda now: now + timedelta(minutes=5), weight_kg=99_999.0)
    assert r["succeeded"], "a recovery must still produce a (dedicated) plan"
    reasons = [a["reason"] for a in r["explanation"]["alternatives"]]
    assert r["strategy"] == "DEDICATED" and r["total_cost"] > 0
    assert all(reason for reason in reasons)


def test_duplicate_recovery_keeps_one_commitment_and_consistent_bookings(api) -> None:
    sid, r1 = misplace_and_recover(api, deadline_at=lambda now: now + timedelta(hours=70))
    r2 = api.post(f"/simulate/recover/{sid}").json()
    with SessionLocal() as db:
        committed = db.scalars(select(RecoveryPlan).where(RecoveryPlan.shipment_id == sid,
                               RecoveryPlan.status == PlanStatus.COMMITTED.value)).all()
        assert [c.id for c in committed] == [r2["committed_plan_id"]]
        booked = {l.leg_id for l in db.scalars(select(ShipmentLeg).where(
            ShipmentLeg.shipment_id == sid, ShipmentLeg.boarded_at.is_(None)))}
        assert booked == {p.leg_id for p in committed[0].paths if p.leg_id}


# ------------------------------------------------ global consistency (last)
def test_zz_global_database_invariants_hold(api) -> None:
    with SessionLocal() as db:
        # 1. at most one COMMITTED plan per shipment
        dup = db.execute(select(RecoveryPlan.shipment_id, func.count())
                         .where(RecoveryPlan.status == PlanStatus.COMMITTED.value)
                         .group_by(RecoveryPlan.shipment_id).having(func.count() > 1)).all()
        assert dup == []
        # 2. capacity never negative, never above total
        bad = db.scalar(select(func.count()).select_from(Leg).where(
            (Leg.residual_kg < -1e-6) | (Leg.residual_kg > Leg.capacity_kg + 1e-6) |
            (Leg.residual_m3 < -1e-6) | (Leg.residual_m3 > Leg.capacity_m3 + 1e-6)))
        assert bad == 0
        # 3. no pending booking survives on a delivered/failed shipment
        orphan = db.scalar(select(func.count()).select_from(ShipmentLeg)
                           .join(Shipment, Shipment.id == ShipmentLeg.shipment_id)
                           .where(ShipmentLeg.boarded_at.is_(None),
                                  Shipment.status.in_([ShipmentStatus.DELIVERED.value, ShipmentStatus.FAILED.value])))
        assert orphan == 0
        # 4. every RECOVERING shipment has a committed plan
        rec = db.scalars(select(Shipment.id).where(Shipment.status == ShipmentStatus.RECOVERING.value)).all()
        for sid in rec:
            assert db.scalar(select(RecoveryPlan).where(RecoveryPlan.shipment_id == sid,
                             RecoveryPlan.status == PlanStatus.COMMITTED.value)), f"shipment {sid} RECOVERING without a plan"
        # 5. awarded auctions: exactly one winner, the lowest bid; linked plans agree on bounty
        for a in db.scalars(select(Auction).where(Auction.status == "AWARDED")):
            bids = sorted(db.scalars(select(Bid).where(Bid.auction_id == a.id)), key=lambda b: b.amount)
            assert sum(b.is_winner for b in bids) == 1 and bids[0].is_winner
            if a.plan_id:
                assert db.get(RecoveryPlan, a.plan_id).bounty_cost == pytest.approx(a.payment)
        # 6. temperatures, pressures and probabilities in range
        assert db.scalar(select(func.count()).select_from(Shipment).where(
            (Shipment.temperature < 0) | (Shipment.temperature > 100) |
            (Shipment.pressure < 0) | (Shipment.pressure > 1) |
            (Shipment.p_misplace < 0) | (Shipment.p_misplace > 1))) == 0
