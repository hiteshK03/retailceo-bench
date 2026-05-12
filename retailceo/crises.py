"""Crisis catalogue -- 3 named crises (C1..C3).

Each CrisisEvent records:
    crisis_id, name, started_day, duration_days, severity,
    affected={demand_mult, supply_mult, sla_mult, opex_bump_inr,
             region, category, nps_bump, cash_bump_inr, ...},
    active, description.

Public API:
    CRISIS_NAMES                     : id -> short name
    schedule_crises(rng, crisis_prob, dept_drifts, cities, days_in_quarter)
                                     -> List[CrisisEvent]  (sorted by start_day)
    is_active(crisis, day)           -> bool
    tick_crisis_active(queue, day)   -> (newly_firing, newly_expired) lists,
                                       mutates `active` flags in place
    crisis_effects_today(active_now) -> aggregated effects dict for ledger + demand
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from retailceo.models import CrisisEvent
from retailceo import economics as E


# ---------------------------------------------------------------------------
# Crisis registry
# ---------------------------------------------------------------------------

CRISIS_NAMES: Dict[str, str] = {
    "C1":  "Diwali demand surge",
    "C2":  "Monsoon flood",
    "C3":  "JioMart enters our city",
    "C4":  "Fuel Price Spike",
    "C5":  "UPI Payment Outage",
    "C6":  "Quick-Commerce Entry",
}


# ---------------------------------------------------------------------------
# Individual builders
# ---------------------------------------------------------------------------

def _scale_mult(mult: float) -> float:
    """Soften (or amplify) a multiplier toward 1.0 by CRISIS_INTENSITY_SCALE."""
    return 1.0 + (mult - 1.0) * E.CRISIS_INTENSITY_SCALE


def _build_c1(day: int, rng: random.Random, cities: List[str]) -> CrisisEvent:
    return CrisisEvent(
        crisis_id="C1",
        name=CRISIS_NAMES["C1"],
        started_day=day,
        duration_days=rng.randint(8, 14),
        severity="high",
        affected={
            "category": "ALL",
            "demand_mult": _scale_mult(1.35),   # festival uplift, scaled
            "nps_bump": +1.0,
        },
        description=(
            "Diwali week is here. Tier-2 families are buying across wheat flour, sweets, "
            "soaps, lights -- footfall climbs into the salary window."
        ),
    )


def _build_c2(day: int, rng: random.Random, cities: List[str]) -> CrisisEvent:
    region = rng.choice(cities)
    return CrisisEvent(
        crisis_id="C2",
        name=CRISIS_NAMES["C2"],
        started_day=day,
        duration_days=rng.randint(5, 12),
        severity="high",
        affected={
            "region": region,
            "category": "fresh",
            "supply_mult": _scale_mult(0.55),
            "sla_mult":    _scale_mult(0.70),
            "demand_mult": _scale_mult(0.85),
            "opex_bump_inr": 40_000.0 * E.CRISIS_INTENSITY_SCALE,
        },
        description=(
            f"Monsoon flood has shut roads into {region}. Dairy and produce supply "
            f"is constrained; rider throughput slips; customers shift online."
        ),
    )


def _build_c3(day: int, rng: random.Random, cities: List[str]) -> CrisisEvent:
    region = rng.choice(cities)
    return CrisisEvent(
        crisis_id="C3",
        name=CRISIS_NAMES["C3"],
        started_day=day,
        duration_days=rng.randint(30, 60),  # long-lasting effect
        severity="high",
        affected={
            "region": region,
            "category": "ALL",
            "demand_mult":          _scale_mult(0.88),
            "share_drain_bump_pct": 6.0 * E.CRISIS_INTENSITY_SCALE,
        },
        description=(
            f"JioMart has launched dark stores in {region} with Rs.99 subscription "
            f"pricing. Price-sensitive customers are testing the app; share drain "
            f"estimated unless retention activates."
        ),
    )


def _build_c4(day: int, rng: random.Random, cities: List[str]) -> CrisisEvent:
    return CrisisEvent(
        crisis_id="C4",
        name=CRISIS_NAMES["C4"],
        started_day=day,
        duration_days=rng.randint(21, 28),
        severity="med",
        affected={
            "category": "ALL",
            "opex_bump_inr": E.BASELINE_WEEKLY_OPEX_INR * 0.10 / 7,
            "cogs_mult": {"fresh": 1.08, "grocery_staple": 1.04},
        },
        description=(
            "Diesel prices have surged 18%. Logistics and cold-chain costs "
            "are climbing; perishable sourcing is hit hardest."
        ),
    )


def _build_c5(day: int, rng: random.Random, cities: List[str]) -> CrisisEvent:
    return CrisisEvent(
        crisis_id="C5",
        name=CRISIS_NAMES["C5"],
        started_day=day,
        duration_days=rng.randint(2, 5),
        severity="high",
        affected={
            "category": "ALL",
            "payment_friction_pct": 0.35,
            "nps_bump": -2.0,
        },
        description=(
            "Major UPI infrastructure failure — 35% of digital transactions "
            "are failing. Cash-only customers are unaffected but digital-first "
            "shoppers are leaving carts."
        ),
    )


def _build_c6(day: int, rng: random.Random, cities: List[str]) -> CrisisEvent:
    region = rng.choice(cities)
    return CrisisEvent(
        crisis_id="C6",
        name=CRISIS_NAMES["C6"],
        started_day=day,
        duration_days=rng.randint(40, 80),
        severity="med",
        affected={
            "region": region,
            "share_drain_bump_pct": 4.0,
            "demand_mult": 0.91,
            "category": "fmcg",
        },
        description=(
            f"Blinkit/Zepto has launched 10-minute delivery in {region}. "
            f"FMCG and fresh categories face share erosion from speed-focused "
            f"competitors."
        ),
    )


CRISIS_BUILDERS = {
    "C1": _build_c1, "C2": _build_c2, "C3": _build_c3,
    "C4": _build_c4, "C5": _build_c5, "C6": _build_c6,
}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def schedule_crises(
    rng: random.Random,
    crisis_prob: float,
    dept_drifts: Dict[str, float],
    cities: List[str],
    days_in_quarter: int = 84,
    day_offset: int = 0,
) -> List[CrisisEvent]:
    """Schedule 1-2 crises across a quarter.

    Args:
        rng              : seeded RNG
        crisis_prob      : probability weight in [0.5, 1.0]
        dept_drifts      : per-dept drift (0..1) -- kept for API parity
        cities           : company's current city list (for regional crises)
        days_in_quarter  : quarter length in days (default 84 = 12 weeks)
        day_offset       : absolute day offset for multi-quarter episodes
                           (crises in Q2 start at day_offset+relative_day)

    Scheduling logic:
        * C1 Diwali is the anchor chapter; fires with prob 0.92 * crisis_prob
          in the latter half of the quarter (day 62%-86% of quarter).
        * One ambient crisis from (C2, C3) fills the early act
          (day 9%-54% of quarter).
    """
    out: List[CrisisEvent] = []

    # Anchor: C1 Diwali  (original: day 35-48 out of 56 = 62%-86%)
    if rng.random() < 0.92 * crisis_prob:
        lo = max(1, int(days_in_quarter * 35 / 56))
        hi = max(lo, int(days_in_quarter * 48 / 56))
        day = day_offset + rng.randint(lo, hi)
        out.append(_build_c1(day, rng, cities))

    # 1 ambient crisis from (C2, C3)  (original: day 5-30 out of 56 = 9%-54%)
    if rng.random() < crisis_prob * 0.85:
        cid = rng.choice(["C2", "C3"])
        lo = max(1, int(days_in_quarter * 5 / 56))
        hi = max(lo, int(days_in_quarter * 30 / 56))
        day = day_offset + rng.randint(lo, hi)
        out.append(CRISIS_BUILDERS[cid](day, rng, cities))

    # C4: Fuel Price Spike
    if rng.random() < 0.70 * crisis_prob:
        lo = max(1, int(days_in_quarter * 10 / 91))
        hi = max(lo, int(days_in_quarter * 60 / 91))
        day = day_offset + rng.randint(lo, hi)
        out.append(_build_c4(day, rng, cities))

    # C5: UPI Payment Outage
    if rng.random() < 0.60 * crisis_prob:
        lo = max(1, int(days_in_quarter * 5 / 91))
        hi = max(lo, int(days_in_quarter * 70 / 91))
        day = day_offset + rng.randint(lo, hi)
        out.append(_build_c5(day, rng, cities))

    # C6: Quick-Commerce Entry
    if rng.random() < 0.75 * crisis_prob:
        lo = max(1, int(days_in_quarter * 5 / 91))
        hi = max(lo, int(days_in_quarter * 30 / 91))
        day = day_offset + rng.randint(lo, hi)
        out.append(_build_c6(day, rng, cities))

    out.sort(key=lambda c: c.started_day)
    return out


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def is_active(c: CrisisEvent, day_of_quarter: int) -> bool:
    return c.started_day <= day_of_quarter < c.started_day + c.duration_days


def tick_crisis_active(
    queue: List[CrisisEvent],
    day_of_quarter: int,
) -> Tuple[List[CrisisEvent], List[CrisisEvent]]:
    """Update active/inactive flags based on today's day index.

    Returns (newly_firing, newly_expired) -- only lists crises whose state
    actually transitioned today (so day-1 setup does not spuriously fire
    "expired" events on crises that haven't started yet).
    """
    firing: List[CrisisEvent] = []
    expired: List[CrisisEvent] = []
    for c in queue:
        was_active = c.active
        now_active = is_active(c, day_of_quarter)
        if now_active and not was_active:
            firing.append(c)
        elif was_active and not now_active and day_of_quarter > c.started_day:
            expired.append(c)
        c.active = now_active
    return firing, expired


def active_crises_now(queue: List[CrisisEvent]) -> List[CrisisEvent]:
    return [c for c in queue if c.active]


def crises_starting_in_horizon(
    queue: List[CrisisEvent],
    week: int,
    horizon_weeks: int,
) -> List[CrisisEvent]:
    """Crises scheduled to begin within the next `horizon_weeks` weeks.

    Used by departments.py to file pre-crisis prep POs the week before
    a known surge / shock, so the CEO has a chance to pre-stock.
    """
    today = (week - 1) * 7 + 1
    horizon_end = today + horizon_weeks * 7
    return [
        c for c in queue
        if not c.active and today <= c.started_day < horizon_end
    ]


# ---------------------------------------------------------------------------
# Effects aggregation (per-day, called by environment)
# ---------------------------------------------------------------------------

def crisis_effects_today(active: List[CrisisEvent]) -> Dict[str, Any]:
    """Aggregate effects from all currently-active crises.

    Returns:
        {
            opex_bump_inr:            sum,
            demand_mult_by_category:  {category: mult} (or 'ALL'),
            supply_mult_by_category:  same,
            sla_mult:                 product of all sla_mults,
            nps_bump:                 sum,
            cash_bump_inr:            sum (one-shot on trigger day),
            share_drain_bump_pct:     sum,
            franchise_health_bump:    sum,
            schema_drift:             any bool true,
        }
    """
    out = {
        "opex_bump_inr":           0.0,
        "demand_mult_by_category": {},
        "supply_mult_by_category": {},
        "cogs_mult_by_category":   {},
        "sla_mult":                1.0,
        "nps_bump":                0.0,
        "cash_bump_inr":           0.0,
        "share_drain_bump_pct":    0.0,
        "franchise_health_bump":   0.0,
        "payment_friction_pct":    0.0,
        "schema_drift":            False,
    }
    for c in active:
        aff = c.affected or {}
        out["opex_bump_inr"]        += float(aff.get("opex_bump_inr", 0.0))
        out["nps_bump"]             += float(aff.get("nps_bump", 0.0))
        out["cash_bump_inr"]        += float(aff.get("cash_bump_inr", 0.0))
        out["share_drain_bump_pct"] += float(aff.get("share_drain_bump_pct", 0.0))
        out["franchise_health_bump"] += float(aff.get("franchise_health_bump", 0.0))
        out["payment_friction_pct"] = max(
            out["payment_friction_pct"], float(aff.get("payment_friction_pct", 0.0))
        )
        if aff.get("schema_drift"):
            out["schema_drift"] = True
        if aff.get("sla_mult") is not None:
            out["sla_mult"] *= float(aff["sla_mult"])

        category = aff.get("category", "ALL")
        if aff.get("demand_mult") is not None:
            out["demand_mult_by_category"][category] = (
                out["demand_mult_by_category"].get(category, 1.0) * float(aff["demand_mult"])
            )
        if aff.get("supply_mult") is not None:
            out["supply_mult_by_category"][category] = (
                out["supply_mult_by_category"].get(category, 1.0) * float(aff["supply_mult"])
            )
        cogs_mult_raw = aff.get("cogs_mult")
        if isinstance(cogs_mult_raw, dict):
            for cat, mult in cogs_mult_raw.items():
                out["cogs_mult_by_category"][cat] = (
                    out["cogs_mult_by_category"].get(cat, 1.0) * float(mult)
                )

    return out
