"""Exogenous-actor simulators for RetailCEO-Bench.

Each simulator is a pure function that consumes the current ledger + active
crises + RNG and returns demand/event signals for the ledger's daily tick.

Randomness is injected; no RNGs created inside.

Public API:
    customer_daily_demand(...)           -> {category: units_today}
    competitor_weekly_events(...)        -> List[CompetitorEvent]
    active_share_drain_pct(...)          -> decayed aggregate share drain %
    supplier_daily_reliability(...)      -> {sku_id: delivery_mult in [0,1]}
    franchisee_weekly_complaints(...)    -> List[Complaint]
    rider_daily_sla_hit_rate(...)        -> float in [0, 100]
    update_weekly_nps(prev, signals)     -> float
    update_weekly_basket_size(prev, ...) -> float
    update_weekly_footfall(prev, ...)    -> float
    update_weekly_repeat_purchase(prev, ...) -> float
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from retailceo.models import (
    CompanyLedger,
    CompetitorEvent,
    Complaint,
    CrisisEvent,
)
from retailceo import economics as E


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

def customer_daily_demand(
    ledger: CompanyLedger,
    day_of_quarter: int,
    nps: float,
    share_drain_pct: float,
    active_crises: List[CrisisEvent],
    rng: random.Random,
    pending_revenue_mult: float = 1.0,
    episode_day: Optional[int] = None,
) -> Dict[str, float]:
    """Compute today's demand in units per category across the network."""
    baseline_daily = E.BASELINE_WEEKLY_REVENUE_INR / 7.0

    salary_mult = E.salary_cycle_multiplier(day_of_quarter)
    dow = ((day_of_quarter - 1) % 7) + 1
    dow_mult = 1.15 if dow in (6, 7) else 1.00

    nps_mult = 1.0 + (nps - E.STARTING_NPS) * 0.003
    competitor_mult = max(0.70, 1.0 - share_drain_pct / 100.0)
    noise = rng.uniform(0.92, 1.08)

    global_mult = salary_mult * dow_mult * nps_mult * competitor_mult * noise * pending_revenue_mult

    if episode_day is not None:
        fest = E.festival_for_episode_day(episode_day)
    else:
        fest = E.festival_for_day(day_of_quarter)

    demand: Dict[str, float] = {}
    for category, share in E.CATEGORY_REVENUE_SHARE.items():
        category_revenue = baseline_daily * share * global_mult

        if fest:
            applies = (
                "ALL" in fest.get("regions", [])
                or (fest.get("regions") and any(r in ledger.cities for r in fest["regions"]))
            )
            if applies and (fest["categories"] == ["ALL"] or category in fest["categories"]):
                region_scale = 1.0 if "ALL" in fest.get("regions", []) else 0.55
                category_revenue *= 1.0 + (fest["demand_mult"] - 1.0) * region_scale

        for crisis in active_crises:
            if not crisis.active:
                continue
            affected = crisis.affected or {}
            cat_match = affected.get("category") in (category, "ALL", None)
            if cat_match and affected.get("demand_mult") is not None:
                category_revenue *= float(affected["demand_mult"])

        avg_price = _avg_price_per_category(category, ledger)
        demand[category] = max(0.0, category_revenue / max(1.0, avg_price))

    return demand


def _avg_price_per_category(category: str, ledger: CompanyLedger) -> float:
    prices = [sku["price_inr"] for sku in ledger.sku_catalogue.values() if sku["category"] == category]
    return sum(prices) / len(prices) if prices else 100.0


# ---------------------------------------------------------------------------
# Competitor
# ---------------------------------------------------------------------------

def competitor_weekly_events(
    ledger: CompanyLedger,
    week_of_quarter: int,
    rng: random.Random,
) -> List[CompetitorEvent]:
    """Generate 0-3 competitor events this week.

    Quick-commerce companies (JioMart / Blinkit / Zepto) act more aggressively
    as the festive quarter progresses.  Impact ranges from 0.5-4.0 percentage
    points of share.
    """
    events: List[CompetitorEvent] = []
    p_event = 0.35 + 0.025 * week_of_quarter
    p_event = min(0.85, p_event)

    while rng.random() < p_event and len(events) < 3:
        event_type = rng.choices(
            ["price_cut", "dark_store_open", "city_entry", "loyalty_push", "bulk_ad"],
            weights=[0.32, 0.22, 0.14, 0.22, 0.10],
        )[0]
        competitor = rng.choices(
            ["JioMart", "Blinkit", "Zepto", "DMart", "Reliance Fresh"],
            weights=[0.28, 0.22, 0.18, 0.18, 0.14],
        )[0]
        region_pool = ledger.cities + ["NCR", "Kolkata", "Bhubaneswar"]
        region = rng.choice(region_pool)
        impact_pct = round(rng.uniform(0.5, 4.0), 2)
        events.append(CompetitorEvent(
            competitor=competitor,
            event_type=event_type,
            region=region,
            impact_pct=impact_pct,
            week=week_of_quarter,
            description=(
                f"{competitor} {event_type.replace('_', ' ')} in {region} "
                f"(~{impact_pct:.1f}pt share impact)"
            ),
        ))
        p_event *= 0.45

    return events


def active_share_drain_pct(
    recent_events: List[CompetitorEvent],
    current_week: int,
    decay_per_week: float = 0.6,
) -> float:
    """Decayed-aggregate share drain from competitor events within the last ~3 weeks.

    Capped at 15 pts so the customer demand multiplier never drops below 0.85.
    """
    total = 0.0
    for ev in recent_events:
        age_weeks = max(0, current_week - ev.week)
        total += ev.impact_pct * (decay_per_week ** age_weeks)
    return min(15.0, total)


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------

def supplier_daily_reliability(
    ledger: CompanyLedger,
    day_of_quarter: int,
    active_crises: List[CrisisEvent],
    rng: random.Random,
) -> Dict[str, float]:
    """Per-SKU PO-delivery multiplier today.

    Mostly 0.92-0.98; dips under monsoon (perishables) or active supply-chain
    crises.
    """
    monsoon_hit = rng.random() < 0.04
    mult: Dict[str, float] = {}

    for sku_id, sku in ledger.sku_catalogue.items():
        reliability = 0.92 + rng.uniform(-0.05, 0.06)
        if monsoon_hit and E.CATEGORY_PERISHABLE[sku["category"]]:
            reliability *= E.MONSOON_SUPPLY_DAMPENER

        for crisis in active_crises:
            if not crisis.active:
                continue
            affected = crisis.affected or {}
            if affected.get("supply_mult") is not None:
                if affected.get("category") in (sku["category"], "ALL", None):
                    reliability *= float(affected["supply_mult"])

        mult[sku_id] = max(0.20, min(1.00, reliability))

    return mult


# ---------------------------------------------------------------------------
# Franchisee
# ---------------------------------------------------------------------------

COMPLAINT_ISSUE_POOL: List[str] = [
    "wheat flour delivery delayed 3 days",
    "POS app crashed during salary-day rush",
    "discount code settlement stuck",
    "expired stock sent in last delivery",
    "price changed without 24h notice",
    "staff training session never happened",
    "delivery SLA missed 2 days running",
    "HQ promo squeezed franchise margin",
    "cold-chain reefer missed Sunday visit",
    "dry run of new planogram confused customers",
    "shrinkage audit team never showed",
    "receivables settlement 10 days late",
]


def franchisee_weekly_complaints(
    ledger: CompanyLedger,
    week_of_quarter: int,
    stockout_rate_by_category: Dict[str, float],
    sla_hit_rate_pct: float,
    rng: random.Random,
) -> List[Complaint]:
    """Franchise complaints driven by health score + systemic pain (stockouts, SLA)."""
    complaints: List[Complaint] = []

    avg_stockout = (
        sum(stockout_rate_by_category.values()) / max(1, len(stockout_rate_by_category))
        if stockout_rate_by_category
        else 0.0
    )
    high_pain = avg_stockout > 10.0 or sla_hit_rate_pct < 85.0

    for fr in ledger.franchisees:
        p_complaint = (1.0 - fr["health_score"]) * 0.25
        if high_pain:
            p_complaint += 0.18

        if rng.random() < p_complaint:
            severity_roll = rng.random()
            if severity_roll < 0.15:
                severity = "high"
            elif severity_roll < 0.55:
                severity = "med"
            else:
                severity = "low"

            complaints.append(Complaint(
                franchise_id=fr["franchise_id"],
                city=fr["city"],
                issue=rng.choice(COMPLAINT_ISSUE_POOL),
                severity=severity,
                week_filed=week_of_quarter,
            ))

            # Health score drifts down a notch when a complaint is filed
            fr["health_score"] = max(0.0, fr["health_score"] - 0.02)
            fr["complaints_open"] = int(fr.get("complaints_open", 0)) + 1

    return complaints


# ---------------------------------------------------------------------------
# Rider (delivery SLA)
# ---------------------------------------------------------------------------

def rider_daily_sla_hit_rate(
    day_of_quarter: int,
    active_crises: List[CrisisEvent],
    rng: random.Random,
) -> float:
    """Today's SLA hit rate in %.  Default ~ 88-92%; tanks under strikes or monsoon."""
    base = E.STARTING_SLA_HIT_RATE_PCT * rng.uniform(0.96, 1.02)

    for crisis in active_crises:
        if not crisis.active:
            continue
        affected = crisis.affected or {}
        if affected.get("sla_mult") is not None:
            base *= float(affected["sla_mult"])

    return max(45.0, min(99.0, base))


# ---------------------------------------------------------------------------
# Weekly KPI updaters (NPS, basket, footfall, repeat)
# ---------------------------------------------------------------------------

def update_weekly_nps(
    prev_nps: float,
    stockout_rate_pct: float,
    sla_hit_rate_pct: float,
    pending_nps_delta: float,
    high_severity_complaints: int,
    rng: random.Random,
) -> float:
    """Drift NPS week-over-week based on operational + marketing signals.

    NPS is bidirectional: pain pushes it down, but when ops are clean it
    regresses toward the starting baseline so a CEO who fixes a crisis
    actually sees recovery (rather than NPS being a one-way trapdoor).
    """
    new_nps = prev_nps
    new_nps -= 0.5 * max(0.0, stockout_rate_pct - 5.0)
    new_nps -= 0.3 * max(0.0, 90.0 - sla_hit_rate_pct)
    new_nps += pending_nps_delta
    new_nps -= 0.6 * high_severity_complaints

    # Recovery toward baseline when stockouts are under control
    if stockout_rate_pct < 10.0:
        new_nps += E.NPS_RECOVERY_RATE * (E.STARTING_NPS - prev_nps)

    new_nps += rng.uniform(-0.8, 0.8)
    return max(0.0, min(80.0, new_nps))


def update_weekly_basket_size(
    prev_basket_inr: float,
    stockout_rate_pct: float,
    festival_weight: float,
    rng: random.Random,
) -> float:
    """Basket size drifts down under stockouts, up on festival weeks."""
    new_basket = prev_basket_inr
    new_basket *= 1.0 - 0.005 * max(0.0, stockout_rate_pct - 5.0)
    new_basket *= 1.0 + 0.08 * festival_weight
    new_basket *= rng.uniform(0.97, 1.03)
    return max(200.0, min(1200.0, new_basket))


def update_weekly_footfall(
    prev_footfall: float,
    share_drain_pct: float,
    festival_weight: float,
    stockout_rate_pct: float,
    rng: random.Random,
) -> float:
    """Average footfall per store per day (weekly avg)."""
    new_ff = prev_footfall
    new_ff *= 1.0 - 0.015 * share_drain_pct
    new_ff *= 1.0 + 0.22 * festival_weight
    new_ff *= 1.0 - 0.006 * max(0.0, stockout_rate_pct - 5.0)  # word-of-mouth lag
    new_ff *= rng.uniform(0.96, 1.04)
    return max(150.0, min(1500.0, new_ff))


def update_weekly_repeat_purchase(
    prev_repeat_pct: float,
    nps: float,
    pending_loyalty_boost: float,
    rng: random.Random,
) -> float:
    """Repeat-purchase rate tracks NPS with lag plus active loyalty programs."""
    target = 30.0 + 0.35 * nps
    new_repeat = prev_repeat_pct + 0.3 * (target - prev_repeat_pct)
    new_repeat += pending_loyalty_boost
    new_repeat += rng.uniform(-1.0, 1.0)
    return max(15.0, min(70.0, new_repeat))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def festival_weight_for_week(week_of_quarter: int) -> float:
    """Return a rough in-[0,1] festive weight for the given week.

    Used to feed basket/footfall updaters.  Based on FESTIVAL_CALENDAR density.
    """
    start_day = (week_of_quarter - 1) * 7 + 1
    end_day = week_of_quarter * 7
    total = 0.0
    for d in range(start_day, end_day + 1):
        fest = E.festival_for_day(d)
        if fest:
            total += max(0.0, fest["demand_mult"] - 1.0)
    return min(1.0, total / 3.0)
