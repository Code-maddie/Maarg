"""E8 — Explainer.

Produces the counterfactual audit trail: what was chosen, what was rejected,
and — concretely — why. SH.docx §5.2 requires this rendered "as a readable
card, not raw JSON", so the output is structured prose plus evidence rather
than a dump of internal state.

Two rules govern everything here:

  1. **Determinism.** The same inputs must always produce the same
     explanation, word for word. A dispatcher who reloads the page must not
     see a different justification, and an audit trail that varies is not an
     audit trail. Nothing here samples, shuffles, or reads the clock.

  2. **No placeholders.** Every rejected alternative carries the actual
     reason the engine recorded. If a reason is missing, that is a bug in the
     engine that produced it, and this module says so explicitly rather than
     inventing a plausible-sounding excuse.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from app.engines.e2_foresight.reservation import ReservationDecision
from app.engines.e4_temperature.cascade import CascadeResult
from app.engines.e4_temperature.engine import TemperatureBreakdown
from app.engines.e4_temperature.pressure import PressureBreakdown
from app.engines.e5_bounty.market import AuctionOutcome
from app.engines.e6_piggy_router.fusion import FusionResult
from app.engines.e6_piggy_router.router import CandidatePlan
from app.models.enums import PlanStrategy

MISSING_REASON = (
    "No reason was recorded by the engine that rejected this plan "
    "(this indicates a defect, not an absent explanation)"
)


@dataclass
class LegEvidence:
    """Concrete facts about one hop, for the route table in the UI."""

    leg_id: Optional[int]
    from_hub: str
    to_hub: str
    departure_at: Optional[str]
    arrival_at: Optional[str]
    cost: float
    is_dedicated: bool

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AlternativeExplanation:
    """One rejected candidate and the real reason it lost."""

    strategy: str
    total_cost: float
    transfers: int
    arrival_at: Optional[str]
    reason: str
    cost_delta: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Explanation:
    """The full counterfactual audit trail for one recovery decision."""

    shipment_id: Optional[int]
    shipment_code: str
    headline: str
    strategy: str
    total_cost: float
    arrival_at: Optional[str]
    deadline_at: Optional[str]
    transfers: int
    slack_hours: Optional[float]
    why_chosen: List[str] = field(default_factory=list)
    route: List[LegEvidence] = field(default_factory=list)
    alternatives: List[AlternativeExplanation] = field(default_factory=list)
    urgency: Dict[str, Any] = field(default_factory=dict)
    market: Dict[str, Any] = field(default_factory=dict)
    foresight: Dict[str, Any] = field(default_factory=dict)
    cascade: Dict[str, Any] = field(default_factory=dict)
    fusion: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "shipment_id": self.shipment_id,
            "shipment_code": self.shipment_code,
            "headline": self.headline,
            "strategy": self.strategy,
            "total_cost": self.total_cost,
            "arrival_at": self.arrival_at,
            "deadline_at": self.deadline_at,
            "transfers": self.transfers,
            "slack_hours": self.slack_hours,
            "why_chosen": list(self.why_chosen),
            "route": [leg.as_dict() for leg in self.route],
            "alternatives": [alt.as_dict() for alt in self.alternatives],
            "urgency": dict(self.urgency),
            "market": dict(self.market),
            "foresight": dict(self.foresight),
            "cascade": dict(self.cascade),
            "fusion": dict(self.fusion),
        }


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="minutes") if value else None


def _hub_name(hub_id: int, hub_names: Dict[int, str]) -> str:
    return hub_names.get(hub_id, f"Hub {hub_id}")


def build_route_evidence(
    plan: CandidatePlan, hub_names: Dict[int, str]
) -> List[LegEvidence]:
    """Turns a plan's legs into the route table the dispatcher sees."""
    return [
        LegEvidence(
            leg_id=leg.leg_id,
            from_hub=_hub_name(leg.from_hub_id, hub_names),
            to_hub=_hub_name(leg.to_hub_id, hub_names),
            departure_at=_iso(leg.departure_at),
            arrival_at=_iso(leg.arrival_at),
            cost=round(leg.edge_cost, 2),
            is_dedicated=leg.is_dedicated,
        )
        for leg in plan.legs
    ]


def explain_alternatives(
    chosen: CandidatePlan,
    rejected: Sequence[CandidatePlan],
    also_ran: Sequence[CandidatePlan] = (),
) -> List[AlternativeExplanation]:
    """Explains every plan that was not chosen.

    Covers two groups: plans the engine rejected outright (which carry a
    rejection reason) and feasible plans that simply scored lower (which do
    not, so a comparative reason is derived from the numbers).
    """
    explanations: List[AlternativeExplanation] = []

    for plan in rejected:
        explanations.append(
            AlternativeExplanation(
                strategy=plan.strategy,
                total_cost=plan.total_cost,
                transfers=plan.transfers,
                arrival_at=_iso(plan.arrival_at),
                reason=plan.rejection_reason or MISSING_REASON,
                cost_delta=(
                    round(plan.total_cost - chosen.total_cost, 2)
                    if plan.total_cost
                    else None
                ),
            )
        )

    for plan in also_ran:
        if plan is chosen:
            continue

        delta = round(plan.total_cost - chosen.total_cost, 2)
        if delta > 0:
            reason = (
                f"Feasible but {delta:.2f} more expensive than the selected "
                f"plan ({plan.total_cost:.2f} vs {chosen.total_cost:.2f})"
            )
        elif plan.transfers > chosen.transfers:
            reason = (
                f"Cheaper by {abs(delta):.2f} but requires "
                f"{plan.transfers} transfers against {chosen.transfers}, "
                "raising handling risk"
            )
        elif plan.arrival_at and chosen.arrival_at and plan.arrival_at > chosen.arrival_at:
            reason = (
                f"Cheaper by {abs(delta):.2f} but arrives "
                f"{_iso(plan.arrival_at)} against {_iso(chosen.arrival_at)}"
            )
        else:
            reason = (
                f"Scored {plan.score:.3f} against the selected plan's "
                f"{chosen.score:.3f} on the combined cost, slack and "
                "transfer ranking"
            )

        explanations.append(
            AlternativeExplanation(
                strategy=plan.strategy,
                total_cost=plan.total_cost,
                transfers=plan.transfers,
                arrival_at=_iso(plan.arrival_at),
                reason=reason,
                cost_delta=delta,
            )
        )

    return explanations


def _why_chosen(
    chosen: CandidatePlan,
    alternatives: Sequence[CandidatePlan],
    deadline: Optional[datetime],
    temperature: Optional[TemperatureBreakdown],
    pressure: Optional[PressureBreakdown] = None,
) -> List[str]:
    """The positive case for the selected plan, in plain sentences."""
    reasons: List[str] = []

    if pressure is not None and pressure.emergency:
        reasons.append(
            f"Emergency Recovery Mode: pressure {pressure.pressure:.2f} is at or "
            "above the threshold, so the fastest feasible plan was chosen over "
            "the cheapest."
        )

    if chosen.strategy == PlanStrategy.PIGGYBACK.value:
        reasons.append(
            "Rides capacity already scheduled on this corridor, so no "
            "additional vehicle was dispatched."
        )
    elif chosen.strategy == PlanStrategy.DEDICATED.value:
        reasons.append(
            "No existing capacity could meet the deadline, so a dedicated "
            "vehicle was required."
        )
    elif chosen.strategy == PlanStrategy.PRE_RESERVED.value:
        reasons.append(
            "Exercised a Foresight option bought before the disruption, so "
            "recovery was immediate."
        )

    dedicated = [
        plan for plan in alternatives
        if plan.strategy == PlanStrategy.DEDICATED.value
    ]
    if dedicated and chosen.strategy != PlanStrategy.DEDICATED.value:
        saving = dedicated[0].total_cost - chosen.total_cost
        if saving > 0:
            pct = 100.0 * saving / dedicated[0].total_cost
            reasons.append(
                f"Costs {chosen.total_cost:.2f} against {dedicated[0].total_cost:.2f} "
                f"for dedicated recovery, a saving of {saving:.2f} ({pct:.1f}%)."
            )

    if chosen.arrival_at and deadline:
        slack = (deadline - chosen.arrival_at).total_seconds() / 3600.0
        if slack >= 0:
            reasons.append(
                f"Arrives {_iso(chosen.arrival_at)}, {slack:.1f} hours "
                f"inside the {_iso(deadline)} deadline."
            )
        else:
            reasons.append(
                f"Arrives {_iso(chosen.arrival_at)}, {abs(slack):.1f} hours "
                f"past the {_iso(deadline)} deadline — this was the best "
                "available option."
            )

    if chosen.transfers == 0:
        reasons.append("Requires no transfers, minimising handling risk.")
    else:
        reasons.append(
            f"Requires {chosen.transfers} transfer(s), each with a minimum "
            "connection allowance."
        )

    if temperature is not None:
        reasons.append(
            f"Priced at lambda = {temperature.lam:.2f}/hour from a "
            f"temperature of {temperature.temperature:.1f} "
            f"({temperature.zone}) under the {temperature.policy_mode} policy."
        )

    return reasons


def explain(
    *,
    shipment_code: str,
    chosen: CandidatePlan,
    rejected: Sequence[CandidatePlan] = (),
    also_ran: Sequence[CandidatePlan] = (),
    hub_names: Optional[Dict[int, str]] = None,
    deadline: Optional[datetime] = None,
    shipment_id: Optional[int] = None,
    temperature: Optional[TemperatureBreakdown] = None,
    pressure: Optional[PressureBreakdown] = None,
    auction: Optional[AuctionOutcome] = None,
    reservation: Optional[ReservationDecision] = None,
    cascade: Optional[CascadeResult] = None,
    fusion: Optional[FusionResult] = None,
) -> Explanation:
    """Builds the complete explanation for one recovery decision."""
    names = hub_names or {}

    slack = None
    if chosen.arrival_at and deadline:
        slack = round((deadline - chosen.arrival_at).total_seconds() / 3600.0, 2)

    headline = (
        f"{shipment_code}: {chosen.strategy} recovery at "
        f"{chosen.total_cost:.2f}"
    )
    if chosen.arrival_at:
        headline += f", arriving {_iso(chosen.arrival_at)}"

    explanation = Explanation(
        shipment_id=shipment_id,
        shipment_code=shipment_code,
        headline=headline,
        strategy=chosen.strategy,
        total_cost=chosen.total_cost,
        arrival_at=_iso(chosen.arrival_at),
        deadline_at=_iso(deadline),
        transfers=chosen.transfers,
        slack_hours=slack,
        why_chosen=_why_chosen(
            chosen, list(rejected) + list(also_ran), deadline, temperature, pressure
        ),
        route=build_route_evidence(chosen, names),
        alternatives=explain_alternatives(chosen, rejected, also_ran),
    )

    if temperature is not None:
        explanation.urgency = {
            "temperature": temperature.temperature,
            "zone": temperature.zone,
            "lambda_per_hour": temperature.lam,
            "policy_mode": temperature.policy_mode,
            "t_base": temperature.t_base,
            "t_time": temperature.t_time,
            "t_delay": temperature.t_delay,
            "t_cascade": temperature.t_cascade,
        }
        if pressure is not None:
            explanation.urgency["pressure"] = pressure.pressure
            explanation.urgency["emergency"] = pressure.emergency

    if auction is not None:
        explanation.market = {
            "auction_id": auction.auction_id,
            "status": auction.status,
            "max_bounty": auction.max_bounty,
            "bid_count": auction.bid_count,
            "lowest_bid": auction.lowest_bid,
            "second_lowest_bid": auction.second_lowest_bid,
            "payment": auction.payment,
            "rule": auction.reason,
        }

    if reservation is not None:
        explanation.foresight = {
            "reserved": reservation.should_reserve,
            "p_misplace": reservation.p_misplace,
            "threshold": reservation.threshold,
            "premium": reservation.premium,
            "expected_saving": reservation.expected_saving,
            "reason": reservation.reason,
        }

    if cascade is not None:
        explanation.cascade = {
            "origin": f"{cascade.origin_type} {cascade.origin_id}",
            "total_affected": cascade.total_affected,
            "shipments_affected": len(cascade.shipments),
            "max_depth_reached": cascade.max_depth_reached,
            "terminated_by": cascade.terminated_by,
        }

    if fusion is not None:
        explanation.fusion = {
            "merged": fusion.merged,
            "cost_saving": fusion.cost_saving,
            "distance_saved_km": fusion.distance_saved_km,
            "utilisation_gain": fusion.utilisation_gain,
            "reason": fusion.reason,
        }

    return explanation
