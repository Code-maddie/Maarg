"""Recovery Orchestrator.

Chains the engines into the single pipeline described in the plan:

    E1 -> E4 -> Pressure -> Cascade -> re-price (E4 + Pressure)
       -> E6 + E7 -> [Emergency ordering] -> E2 -> E5 -> commit + booking -> E8
       -> E9 (recorded on delivery)

E4 runs before Pressure because the Pressure Score reads Temperature.
Route Fusion is a batch operation over several recoveries and is not part of
the single-shipment pipeline.

Design rules:

  * **No engine logic lives here.** The orchestrator sequences engines and
    persists their output; every formula stays in its own module.
  * **A failing engine degrades the pipeline, it does not abort it.** E1 may
    be unloaded, an auction may attract no bids, cascade may find nothing.
    None of those should prevent a plan being produced, so each stage is
    guarded and its failure recorded in ``stages``.
  * **Only the chosen plan is committed.** Alternatives are persisted as
    PROPOSED so E8 can explain them and a dispatcher can override to one.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engines.e1_misplacement.registry import ModelNotReadyError
from app.engines.e1_misplacement.service import E1Service, features_for_shipment
from app.engines.e2_foresight.reservation import (
    ReservationDecision,
    evaluate_shipment as evaluate_reservation,
)
from app.engines.e4_temperature.cascade import CascadeEngine, CascadeResult
from app.engines.e4_temperature.engine import (
    TemperatureBreakdown,
    TemperatureEngine,
)
from app.engines.e4_temperature.pressure import PressureBreakdown, apply_pressure
from app.engines.e5_bounty.market import AuctionOutcome, run_auction
from app.engines.e6_piggy_router.router import CandidatePlan, dedicated_plan
from app.engines.e7_graph_memory.planner import plan_recovery
from app.engines.e8_explainer.explainer import Explanation, explain
from app.engines.e9_learning.outcomes import PredictionSnapshot
from app.models import Auction, Hub, RecoveryPath, RecoveryPlan, Shipment
from app.services.events import EventType, publish
from app.services.notifications import publish_bounty_offer
from app.models.enums import PlanStatus, PlanStrategy, ShipmentStatus

logger = get_logger(__name__)


@dataclass
class StageResult:
    """How one pipeline stage went."""

    name: str
    ok: bool
    ms: float
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "ms": round(self.ms, 3),
                "detail": self.detail}


@dataclass
class RecoveryResult:
    """Everything one full recovery produced."""

    shipment_id: int
    shipment_code: str
    stages: List[StageResult] = field(default_factory=list)
    committed_plan_id: Optional[int] = None
    strategy: Optional[str] = None
    total_cost: float = 0.0
    warm_started: bool = False
    total_ms: float = 0.0

    temperature: Optional[TemperatureBreakdown] = None
    pressure: Optional[PressureBreakdown] = None
    cascade: Optional[CascadeResult] = None
    reservation: Optional[ReservationDecision] = None
    auction: Optional[AuctionOutcome] = None
    explanation: Optional[Explanation] = None
    prediction: Optional[PredictionSnapshot] = None

    @property
    def succeeded(self) -> bool:
        return self.committed_plan_id is not None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "shipment_id": self.shipment_id,
            "shipment_code": self.shipment_code,
            "succeeded": self.succeeded,
            "committed_plan_id": self.committed_plan_id,
            "strategy": self.strategy,
            "total_cost": self.total_cost,
            "warm_started": self.warm_started,
            "total_ms": round(self.total_ms, 3),
            "stages": [stage.as_dict() for stage in self.stages],
            "temperature": self.temperature.as_dict() if self.temperature else None,
            "pressure": self.pressure.as_dict() if self.pressure else None,
            "cascade": self.cascade.as_dict() if self.cascade else None,
            "reservation": self.reservation.as_dict() if self.reservation else None,
            "auction": self.auction.as_dict() if self.auction else None,
            "explanation": self.explanation.as_dict() if self.explanation else None,
        }


class RecoveryOrchestrator:
    """Runs the full recovery pipeline for one shipment."""

    def __init__(
        self,
        db: Session,
        *,
        seed: int = 42,
        e1_service: Optional[E1Service] = None,
    ) -> None:
        self.db = db
        self.rng = random.Random(seed)
        self._e1 = e1_service

    # --- helpers ---------------------------------------------------------

    def _stage(self, result: RecoveryResult, name: str):
        """Context manager recording a stage's timing and outcome."""
        orchestrator = self

        class _Stage:
            def __enter__(self):
                self.started = time.perf_counter()
                self.detail = ""
                return self

            def __exit__(self, exc_type, exc, tb):
                elapsed = (time.perf_counter() - self.started) * 1000
                ok = exc_type is None
                detail = self.detail if ok else f"{exc_type.__name__}: {exc}"
                result.stages.append(
                    StageResult(name=name, ok=ok, ms=elapsed, detail=detail)
                )
                if not ok:
                    logger.warning("Pipeline stage %s failed: %s", name, detail)
                    # Without this the session stays in a failed transaction
                    # and every later stage dies with PendingRollbackError —
                    # one broken stage would take down the whole pipeline,
                    # which is exactly what this guard exists to prevent.
                    try:
                        orchestrator.db.rollback()
                    except Exception:  # noqa: BLE001 - cleanup must not raise
                        logger.exception("Rollback after stage %s failed", name)
                # A failing stage degrades the pipeline; it does not abort it.
                return True

        return _Stage()

    # --- pipeline --------------------------------------------------------

    def recover(
        self,
        shipment: Shipment,
        *,
        now: datetime,
        k: int = 5,
        run_cascade: bool = True,
        run_auction_stage: bool = True,
    ) -> RecoveryResult:
        """Executes the complete pipeline for one misplaced shipment."""
        started = time.perf_counter()
        result = RecoveryResult(
            shipment_id=shipment.id, shipment_code=shipment.code
        )

        hub_names = {
            hub.id: hub.name for hub in self.db.scalars(select(Hub)).all()
        }

        # --- E1: risk ---------------------------------------------------
        with self._stage(result, "E1 misplacement") as stage:
            service = self._e1 or E1Service()
            origin = self.db.get(Hub, shipment.origin_hub_id)
            destination = self.db.get(Hub, shipment.dest_hub_id)
            current = self.db.get(
                Hub, shipment.current_hub_id or shipment.origin_hub_id
            )

            try:
                probability = service.score(
                    features_for_shipment(
                        shipment, origin=origin, dest=destination,
                        current=current, at=now,
                    )
                )
                shipment.p_misplace = probability
                self.db.commit()
                stage.detail = f"P(misplace)={probability:.4f}"
            except ModelNotReadyError as exc:
                # E1 unavailable must not stop a recovery.
                stage.detail = f"E1 unavailable, continuing without risk: {exc}"

        # --- E4: temperature and lambda ---------------------------------
        with self._stage(result, "E4 temperature") as stage:
            engine = TemperatureEngine.from_db(self.db)
            result.temperature = engine.apply(shipment, now)
            self.db.commit()
            stage.detail = (
                f"T={result.temperature.temperature:.1f} "
                f"({result.temperature.zone}), lambda={result.temperature.lam:.2f}"
            )

        # --- Pressure ----------------------------------------------------
        with self._stage(result, "Recovery pressure") as stage:
            result.pressure = apply_pressure(shipment, now)
            self.db.commit()
            stage.detail = (
                f"pressure={result.pressure.pressure:.3f}, "
                f"emergency={result.pressure.emergency}"
            )

        # --- Cascade -----------------------------------------------------
        if run_cascade:
            with self._stage(result, "Recovery cascade") as stage:
                cascade_engine = CascadeEngine(self.db)
                result.cascade = cascade_engine.propagate(
                    origin_type="shipment", origin_id=shipment.id, now=now
                )
                touched = cascade_engine.apply(result.cascade, now=now)
                stage.detail = (
                    f"{result.cascade.total_affected} affected, "
                    f"{len(touched)} shipments updated, "
                    f"terminated by {result.cascade.terminated_by}"
                )

        # Cascade raises cascade_depth, which feeds E4's T_cascade term, so
        # this shipment's own temperature and pressure have moved. Re-read
        # them: otherwise the Explainer would quote the pre-cascade figures
        # while the dispatcher queue shows the post-cascade ones — two
        # different numbers for the same shipment.
        self.db.refresh(shipment)
        if run_cascade and result.cascade is not None:
            with self._stage(result, "Re-price after cascade") as stage:
                engine = TemperatureEngine.from_db(self.db)
                result.temperature = engine.apply(shipment, now)
                result.pressure = apply_pressure(shipment, now)
                self.db.commit()
                stage.detail = (
                    f"T={result.temperature.temperature:.1f}, "
                    f"lambda={result.temperature.lam:.2f}, "
                    f"pressure={result.pressure.pressure:.3f}"
                )

        # --- E6 + E7: routing with warm-start ---------------------------
        outcome = None
        with self._stage(result, "E6 router + E7 memory") as stage:
            outcome = plan_recovery(self.db, shipment, now=now, k=k)
            result.warm_started = outcome.warm_started
            stage.detail = (
                f"{len(outcome.result.plans)} plans, "
                f"{len(outcome.result.rejected)} rejected, "
                f"warm_started={outcome.warm_started}, "
                f"backtracked={outcome.backtracked}, "
                f"{outcome.wall_ms:.2f} ms"
            )

        plans: List[CandidatePlan] = list(outcome.result.plans) if outcome else []
        rejected: List[CandidatePlan] = (
            list(outcome.result.rejected) if outcome else []
        )

        # Guarantee a plan exists. A recovery that returns nothing is worse
        # than an expensive one.
        if not plans:
            with self._stage(result, "Dedicated fallback") as stage:
                origin_hub = self.db.get(
                    Hub, shipment.current_hub_id or shipment.origin_hub_id
                )
                destination_hub = self.db.get(Hub, shipment.dest_hub_id)
                if origin_hub and destination_hub:
                    fallback = dedicated_plan(
                        origin_hub, destination_hub, now, shipment.deadline_at
                    )
                    plans = [fallback]
                    stage.detail = f"dedicated fallback at {fallback.total_cost:.2f}"

        if not plans:
            result.total_ms = (time.perf_counter() - started) * 1000
            logger.warning("Recovery for %s produced no plan", shipment.code)
            return result

        # Emergency Recovery Mode: above the pressure threshold the
        # fastest feasible plan wins over the cheapest. Plans that arrive
        # past the deadline or have no arrival time sort last.
        if result.pressure is not None and result.pressure.emergency and len(plans) > 1:
            with self._stage(result, "Emergency ordering") as stage:
                plans.sort(key=lambda p: (p.arrival_at is None, p.arrival_at or now))
                stage.detail = (
                    f"pressure {result.pressure.pressure:.3f} >= threshold: "
                    f"fastest plan ({plans[0].strategy}) chosen"
                )

        chosen = plans[0]

        # --- E2: foresight ----------------------------------------------
        with self._stage(result, "E2 foresight") as stage:
            dedicated_reference = next(
                (p.total_cost for p in plans
                 if p.strategy == PlanStrategy.DEDICATED.value),
                chosen.total_cost * 2,
            )
            result.reservation = evaluate_reservation(
                shipment,
                dedicated_cost=dedicated_reference,
                expected_bounty=chosen.total_cost,
            )
            stage.detail = (
                f"reserve={result.reservation.should_reserve}, "
                f"threshold={result.reservation.threshold:.3f}"
            )

        # --- E5: bounty market ------------------------------------------
        if run_auction_stage:
            with self._stage(result, "E5 bounty market") as stage:
                dedicated_reference = next(
                    (p.total_cost for p in plans
                     if p.strategy == PlanStrategy.DEDICATED.value),
                    chosen.total_cost * 2,
                )
                hours_saved = 0.0
                if chosen.arrival_at:
                    hours_saved = max(
                        0.0,
                        (shipment.deadline_at - chosen.arrival_at).total_seconds()
                        / 3600.0,
                    )

                result.auction = run_auction(
                    self.db, shipment,
                    now=now,
                    lam=shipment.lam or shipment.sla_penalty_per_hour,
                    hours_saved=hours_saved,
                    dedicated_cost=dedicated_reference,
                    rng=self.rng,
                )
                stage.detail = (
                    f"{result.auction.status}, {result.auction.bid_count} bids, "
                    f"payment={result.auction.payment}"
                )

        # --- persist plans ----------------------------------------------
        with self._stage(result, "Persist plans") as stage:
            committed = self._persist(shipment, plans, rejected, outcome)
            result.committed_plan_id = committed.id
            result.strategy = committed.strategy
            result.total_cost = committed.total_cost
            stage.detail = (
                f"plan {committed.id} committed, "
                f"{len(plans) - 1} alternatives retained"
            )
            if result.auction is not None:
                auction_row = self.db.get(Auction, result.auction.auction_id)
                if auction_row is not None:
                    auction_row.plan_id = committed.id
                committed.bounty_cost = result.auction.payment or 0.0
                self.db.commit()

        # --- E8: explanation ---------------------------------------------
        with self._stage(result, "E8 explainer") as stage:
            result.explanation = explain(
                shipment_code=shipment.code,
                shipment_id=shipment.id,
                chosen=chosen,
                rejected=rejected,
                also_ran=plans[1:],
                hub_names=hub_names,
                deadline=shipment.deadline_at,
                temperature=result.temperature,
                pressure=result.pressure,
                auction=result.auction,
                reservation=result.reservation,
                cascade=result.cascade,
            )
            stage.detail = f"{len(result.explanation.alternatives)} alternatives explained"

        # --- E9: prediction snapshot -------------------------------------
        result.prediction = PredictionSnapshot(
            cost=chosen.total_cost,
            arrival=chosen.arrival_at,
            p_misplace=shipment.p_misplace,
            temperature=shipment.temperature,
            lam=shipment.lam,
            strategy=chosen.strategy,
            plan_id=result.committed_plan_id,
        )

        result.total_ms = (time.perf_counter() - started) * 1000

        publish(
            EventType.PLAN_CHANGED,
            {
                "shipment_id": shipment.id,
                "shipment_code": shipment.code,
                "plan_id": result.committed_plan_id,
                "strategy": result.strategy,
                "total_cost": result.total_cost,
                "warm_started": result.warm_started,
                "total_ms": round(result.total_ms, 2),
            },
            at=now,
        )
        publish(
            EventType.TEMPERATURE_UPDATE,
            {
                "shipment_id": shipment.id,
                "temperature": shipment.temperature,
                "lam": shipment.lam,
                "zone": result.temperature.zone if result.temperature else None,
            },
            at=now,
        )
        publish(
            EventType.PRESSURE_UPDATE,
            {
                "shipment_id": shipment.id,
                "pressure": shipment.pressure,
                "emergency": result.pressure.emergency if result.pressure else False,
            },
            at=now,
        )
        if result.cascade is not None:
            publish(
                EventType.CASCADE_EVENT,
                {
                    "origin": f"{result.cascade.origin_type} {result.cascade.origin_id}",
                    "total_affected": result.cascade.total_affected,
                    "max_depth_reached": result.cascade.max_depth_reached,
                    "terminated_by": result.cascade.terminated_by,
                },
                at=now,
            )
        if result.auction is not None:
            # Drivers listen on Firestore (SH.docx §11). No-op unless
            # FIRESTORE_ENABLED, and never raises.
            publish_bounty_offer(
                result.auction.auction_id,
                status=result.auction.status,
                max_bounty=result.auction.max_bounty,
                shipment_code=shipment.code,
                best_bid=result.auction.lowest_bid,
                winning_vehicle_id=result.auction.winning_vehicle_id,
                payment=result.auction.payment,
            )
            publish(
                EventType.AUCTION_CHANGED,
                {
                    "auction_id": result.auction.auction_id,
                    "status": result.auction.status,
                    "max_bounty": result.auction.max_bounty,
                    "bid_count": result.auction.bid_count,
                    "payment": result.auction.payment,
                },
                at=now,
            )

        logger.info(
            "Recovery for %s complete: %s at %.2f in %.1f ms (%d stages)",
            shipment.code, result.strategy, result.total_cost,
            result.total_ms, len(result.stages),
        )
        return result

    def _persist(
        self,
        shipment: Shipment,
        plans: List[CandidatePlan],
        rejected: List[CandidatePlan],
        outcome,
    ) -> RecoveryPlan:
        """Writes plans to the database; the best is COMMITTED."""
        # Supersede every live plan from an earlier attempt — COMMITTED as
        # well as PROPOSED. Superseding only PROPOSED plans left a shipment
        # with two COMMITTED plans after a re-plan, so the dispatcher would
        # see two "active" recoveries for one shipment.
        previous = self.db.scalars(
            select(RecoveryPlan).where(
                RecoveryPlan.shipment_id == shipment.id,
                RecoveryPlan.status.in_(
                    [PlanStatus.PROPOSED.value, PlanStatus.COMMITTED.value]
                ),
            )
        ).all()
        for stale in previous:
            stale.status = PlanStatus.REJECTED.value
            stale.rejection_reason = "Superseded by a newer recovery attempt"

        # End-to-end planning time (graph build or memory revalidation
        # included) — the honest re-plan latency shown in the UI.
        compute_ms = outcome.wall_ms if outcome else 0.0
        warm = outcome.warm_started if outcome else False

        committed: Optional[RecoveryPlan] = None

        for rank, candidate in enumerate(plans, start=1):
            row = RecoveryPlan(
                shipment_id=shipment.id,
                strategy=candidate.strategy,
                status=(
                    PlanStatus.COMMITTED.value if rank == 1
                    else PlanStatus.PROPOSED.value
                ),
                rank=rank,
                score=candidate.score,
                total_cost=candidate.total_cost,
                eta=candidate.arrival_at,
                transit_hours=candidate.transit_hours,
                compute_ms=compute_ms,
                warm_started=warm,
            )
            row.paths = [
                RecoveryPath(
                    seq=index,
                    leg_id=leg.leg_id,
                    from_hub_id=leg.from_hub_id,
                    to_hub_id=leg.to_hub_id,
                    departure_at=leg.departure_at,
                    arrival_at=leg.arrival_at,
                    edge_cost=leg.edge_cost,
                )
                for index, leg in enumerate(candidate.legs)
            ]
            self.db.add(row)
            if rank == 1:
                committed = row

        # Rejected candidates are persisted too, so the Explainer survives a
        # page reload rather than living only in the response.
        for candidate in rejected:
            self.db.add(
                RecoveryPlan(
                    shipment_id=shipment.id,
                    strategy=candidate.strategy,
                    status=PlanStatus.REJECTED.value,
                    rank=0,
                    score=candidate.score,
                    total_cost=candidate.total_cost,
                    eta=candidate.arrival_at,
                    rejection_reason=candidate.rejection_reason,
                    compute_ms=compute_ms,
                )
            )

        assert committed is not None  # plans is non-empty at this point
        self.db.flush()

        # Physically book the committed plan: consumes leg capacity and puts
        # the shipment on the vehicle, so it actually moves and delivers.
        from app.engines.e7_graph_memory.memory import get_memory
        from app.services.booking import book_plan

        failed = book_plan(self.db, shipment, committed)
        if failed and outcome is not None:
            # Same simulated-time equivalence key the planner used.
            for leg_id in failed:
                get_memory().remember_failed_leg(outcome.query_key, leg_id)

        shipment.status = ShipmentStatus.RECOVERING.value
        self.db.commit()
        return committed


def recover_shipment(
    db: Session,
    shipment: Shipment,
    *,
    now: datetime,
    k: int = 5,
    seed: int = 42,
) -> RecoveryResult:
    """Convenience entry point for one recovery."""
    return RecoveryOrchestrator(db, seed=seed).recover(shipment, now=now, k=k)
