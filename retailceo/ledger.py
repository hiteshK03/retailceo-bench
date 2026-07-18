"""RetailCEO-Bench company-state engine — CompanyLedger factory + daily-tick mutations.

Deterministic arithmetic over the CompanyLedger given exogenous demand signals
(customers), exogenous supply signals (suppliers, monsoon), CEO-approved
proposal effects, and crisis effects.

Ported from SimMart ledger.py.  Changes:
    • Imports from retailceo.models / retailceo.economics
    • dept_approval_streak / dept_rejection_streak removed (Enhancement B, unused)
    • Rogue-related logic removed

Contract:
    • Randomness is injected from outside via a `random.Random` passed by the
      environment (seeded once at reset).  This module does NOT create its own
      RNGs.
    • All mutations happen in-place on the CompanyLedger instance.
    • All ₹ values are floats.

Functions:
    create_initial_ledger(rng)                    → CompanyLedger
    sell_daily_demand(ledger, demand, rng)        → daily sales dict
    apply_daily_overhead(ledger, extra_inr)       → opex ₹ applied
    apply_shrinkage_and_spoilage(ledger, rng)     → loss breakdown dict
    execute_approved_proposals(ledger, proposals, decisions, rng)
                                                  → {applied_cost_inr, inventory_delta, notes}
    tick_one_day(ledger, day, daily_inputs, rng)  → one-day telemetry dict
    snapshot_weekly_kpis(ledger, weekly_agg)      → KPISnapshot (also appended to history)
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from retailceo.models import (
    CompanyLedger,
    KPISnapshot,
    PnLSnapshot,
    Proposal,
    ProposalDecision,
)
from retailceo import economics as E


# Actions whose cash spend should ALSO hit EBITDA via opex (not capitalized
# through inventory or amortized through future revenue). Approving a costly
# action from this set must visibly tank EBITDA — that's how the CEO learns
# to reject negative-EV proposals instead of blanket-approving everything.
OPEX_BEARING_ACTIONS = {
    "staff.schedule", "hours.extend", "return.approve",
    "capex.approve", "campaign.launch", "loyalty.update",
    "brand.ambassador", "strategic.opportunity",
}


def _festival_synergy_mult(week: int, multi_year: bool) -> float:
    """Return a campaign synergy multiplier if any festival falls in the coming week."""
    start_day = (week - 1) * 7 + 1
    for d in range(start_day, start_day + 8):
        if multi_year:
            fest = E.festival_for_episode_day(d)
        else:
            fest = E.festival_for_day(d)
        if fest and fest.get("demand_mult", 1.0) > 1.2:
            return E.FESTIVAL_CAMPAIGN_SYNERGY_MULT
    return 1.0


# ---------------------------------------------------------------------------
# Ledger factory
# ---------------------------------------------------------------------------

def create_initial_ledger(rng: random.Random, difficulty: str = "medium") -> CompanyLedger:
    """Seed a CompanyLedger with starting cash, stores, franchisees, SKUs, inventory.

    Inventory is sized to roughly 14 days of expected demand for staples and
    7 days for perishables.  Values are jittered so episodes with different
    seeds start in slightly different positions.
    """
    ledger = CompanyLedger()
    ledger.cash_inr = E.STARTING_CASH_INR
    ledger.cogs_factor = E.DIFFICULTY_COGS_FACTOR.get(difficulty, 1.0)
    ledger.growth_lever_mult = E.DIFFICULTY_GROWTH_LEVER_MULT.get(difficulty, 1.0)
    ledger.line_of_credit_limit = E.STARTING_LINE_OF_CREDIT_LIMIT_INR
    ledger.line_of_credit_drawn = 0.0
    ledger.pnl_qtd = PnLSnapshot()

    # --- Cities + stores ---
    ledger.cities = list(E.STARTING_CITIES)
    store_counter = 0
    for city in E.STARTING_CITIES:
        for _ in range(E.STORES_PER_CITY[city]):
            store_counter += 1
            ledger.stores.append({
                "store_id": f"S{store_counter:03d}",
                "city": city,
                "sqft": rng.randint(2000, 5000),
                "status": "active",
            })

    # --- Franchisees (~1 per 3 stores; tier-2 chains typically mix owned + franchise) ---
    franchise_counter = 0
    for idx, store in enumerate(ledger.stores):
        if idx % 3 == 0:
            franchise_counter += 1
            ledger.franchisees.append({
                "franchise_id": f"F{franchise_counter:03d}",
                "store_id": store["store_id"],
                "city": store["city"],
                "health_score": round(rng.uniform(0.60, 0.95), 2),
                "complaints_open": 0,
            })

    # --- SKU catalogue (frozen copy) ---
    ledger.sku_catalogue = {k: dict(v) for k, v in E.SKU_CATALOGUE.items()}

    # --- Initial inventory ---
    # Bump initial buffer so weeks 1–2 have slack; depts only catch up over
    # 2-3 weeks of restock POs, and an oracle CEO needs runway to demonstrate
    # competence rather than fighting an unrecoverable starting deficit.
    for sku_id, sku in ledger.sku_catalogue.items():
        category = sku["category"]
        days_of_stock = E.INITIAL_INVENTORY_DAYS_PERISHABLE if E.CATEGORY_PERISHABLE[category] \
            else E.INITIAL_INVENTORY_DAYS_STAPLE
        units_per_store_per_day = _baseline_units_per_store_per_day(category)
        qty = units_per_store_per_day * E.TOTAL_STARTING_STORES * days_of_stock * rng.uniform(0.85, 1.15)
        ledger.inventory[sku_id] = {
            "qty": float(qty),
            "value_inr": float(qty * sku["cost_inr"]),
            "avg_age_days": float(rng.randint(0, 5) if not E.CATEGORY_PERISHABLE[category] else rng.randint(0, 2)),
        }

    return ledger


def _baseline_units_per_store_per_day(category: str) -> float:
    """Baseline units/store/day for inventory seeding.

    Sourced from economics.CATEGORY_BASELINE_UNITS_PER_STORE_PER_DAY which is
    derived from CATEGORY_REVENUE_SHARE and the SKU catalogue, so seeding
    stays in sync with the actual demand model (~14 days cover for staples,
    ~7 for perishables at reset).
    """
    return float(E.CATEGORY_BASELINE_UNITS_PER_STORE_PER_DAY.get(category, 3.0))


# ---------------------------------------------------------------------------
# Daily-tick primitives
# ---------------------------------------------------------------------------

def sell_daily_demand(
    ledger: CompanyLedger,
    category_demand_units: Dict[str, float],
    rng: random.Random,
) -> Dict[str, Any]:
    """Split category-level demand across SKUs and fulfil against inventory.

    Args:
        category_demand_units: {category: total_units_today_across_network}

    Returns:
        {
            revenue_inr:        total ₹ revenue today,
            cogs_inr:           total ₹ cogs today,
            units_sold:         {sku_id: qty_sold},
            stockout_units:     {sku_id: qty_short},
            stockout_rate_pct:  share of SKUs (weighted by demand) that stocked out today,
            units_queried:      dict of total demand attempted per sku (for diagnostics),
        }
    """
    revenue = 0.0
    cogs = 0.0
    units_sold: Dict[str, float] = {}
    stockout_units: Dict[str, float] = {}
    units_queried: Dict[str, float] = {}

    # Counters for stockout rate
    demand_weighted_total = 0.0
    demand_weighted_short = 0.0

    for category, demand_units in category_demand_units.items():
        if demand_units <= 0:
            continue
        category_skus = E.skus_in_category(category)
        if not category_skus:
            continue

        # Allocate category demand across SKUs: uniform with small noise
        noise = [rng.uniform(0.8, 1.2) for _ in category_skus]
        n = len(category_skus)
        sku_demands = [demand_units * noise[i] / sum(noise) for i in range(n)]

        for sku_id, sku_demand in zip(category_skus, sku_demands):
            units_queried[sku_id] = units_queried.get(sku_id, 0.0) + sku_demand
            inv = ledger.inventory.get(sku_id)
            if inv is None:
                stockout_units[sku_id] = stockout_units.get(sku_id, 0.0) + sku_demand
                demand_weighted_total += sku_demand
                demand_weighted_short += sku_demand
                continue

            available = inv["qty"]
            sold = min(sku_demand, available)
            short = max(0.0, sku_demand - available)

            if sold > 0:
                sku = ledger.sku_catalogue.get(sku_id)
                if sku is None:
                    # Phantom inventory row — treat as a stockout so revenue/cogs
                    # accounting stays self-consistent.
                    stockout_units[sku_id] = stockout_units.get(sku_id, 0.0) + sku_demand
                    demand_weighted_short += sku_demand
                    demand_weighted_total += sku_demand
                    continue
                revenue += sold * sku["price_inr"]
                cogs += sold * sku["cost_inr"] * ledger.cogs_factor
                inv["qty"] = max(0.0, available - sold)
                inv["value_inr"] = inv["qty"] * sku["cost_inr"]
                units_sold[sku_id] = units_sold.get(sku_id, 0.0) + sold

            if short > 0:
                stockout_units[sku_id] = stockout_units.get(sku_id, 0.0) + short

            demand_weighted_total += sku_demand
            demand_weighted_short += short

    stockout_rate_pct = (
        (demand_weighted_short / demand_weighted_total) * 100.0
        if demand_weighted_total > 0
        else 0.0
    )

    return {
        "revenue_inr": revenue,
        "cogs_inr": cogs,
        "units_sold": units_sold,
        "stockout_units": stockout_units,
        "stockout_rate_pct": stockout_rate_pct,
        "units_queried": units_queried,
    }


def apply_daily_overhead(ledger: CompanyLedger, extra_inr: float = 0.0) -> float:
    """Deduct today's opex from cash and return the total applied.

    Baseline = weekly baseline / 7. Extras come from crises (e.g. cold-chain
    failure maintenance cost) and department proposals (staff.schedule adds
    payroll).
    """
    daily_opex = E.BASELINE_WEEKLY_OPEX_INR / 7.0 + max(0.0, extra_inr)
    ledger.cash_inr -= daily_opex
    return daily_opex


def apply_shrinkage_and_spoilage(
    ledger: CompanyLedger,
    rng: random.Random,
) -> Dict[str, float]:
    """Apply a small daily shrinkage across all inventory and spoilage for perishables.

    Shrinkage: 2% annual → ~0.0055% daily on inventory value, jittered 0.5× – 1.5×.
    Spoilage: perishables past a 3-day average age lose 3%/day over that threshold,
              capped at 30%/day.

    Returns:
        {shrinkage_value_inr, spoilage_value_inr}
    """
    shrinkage_value = 0.0
    spoilage_value = 0.0

    daily_shrinkage_rate = 0.000055 * rng.uniform(0.5, 1.5)  # 2% annual ≈ 0.0055% daily

    phantom_keys: List[str] = []
    for sku_id, inv in ledger.inventory.items():
        sku = ledger.sku_catalogue.get(sku_id)
        if sku is None:
            # Phantom row (e.g. from a CEO modify with an unknown sku_id that
            # leaked through pre-validation). Skip and queue for cleanup so it
            # cannot crash future ticks or distort KPIs.
            phantom_keys.append(sku_id)
            continue

        # Shrinkage
        loss_qty = inv["qty"] * daily_shrinkage_rate
        shrinkage_value += loss_qty * sku["cost_inr"]
        inv["qty"] = max(0.0, inv["qty"] - loss_qty)

        # Age perishables and spoil beyond threshold
        if E.CATEGORY_PERISHABLE[sku["category"]]:
            inv["avg_age_days"] += 1.0
            if inv["avg_age_days"] > 3.0:
                spoil_rate = min(0.30, 0.03 * (inv["avg_age_days"] - 3.0))
                spoil_qty = inv["qty"] * spoil_rate
                spoilage_value += spoil_qty * sku["cost_inr"]
                inv["qty"] = max(0.0, inv["qty"] - spoil_qty)

        inv["value_inr"] = inv["qty"] * sku["cost_inr"]

    for k in phantom_keys:
        ledger.inventory.pop(k, None)

    return {
        "shrinkage_value_inr": shrinkage_value,
        "spoilage_value_inr": spoilage_value,
    }


def settle_revenue(ledger: CompanyLedger, revenue: float, cogs: float) -> None:
    """Add revenue to cash and record COGS in P&L (cash for COGS already paid at PO time)."""
    ledger.cash_inr += revenue
    ledger.pnl_qtd.revenue_qtd_inr += revenue
    ledger.pnl_qtd.cogs_qtd_inr += cogs
    _recompute_pnl(ledger)


def settle_opex(ledger: CompanyLedger, opex: float) -> None:
    """Record opex in QTD P&L (cash already debited in apply_daily_overhead)."""
    ledger.pnl_qtd.opex_qtd_inr += opex
    _recompute_pnl(ledger)


def _recompute_pnl(ledger: CompanyLedger) -> None:
    pnl = ledger.pnl_qtd
    pnl.ebitda_qtd_inr = pnl.revenue_qtd_inr - pnl.cogs_qtd_inr - pnl.opex_qtd_inr
    pnl.ebitda_margin_pct = (
        (pnl.ebitda_qtd_inr / pnl.revenue_qtd_inr) * 100.0
        if pnl.revenue_qtd_inr > 0
        else 0.0
    )


# ---------------------------------------------------------------------------
# Approved proposal execution
# ---------------------------------------------------------------------------

# Proposals can carry "pending effects" that manifest next week (campaigns,
# discounts, loyalty boosts).  We keep a simple buffer attached to the ledger
# via a well-known key on the SKU catalogue dict (ugly but avoids model churn).
_PENDING_BUFFER_KEY = "__pending_weekly_effects__"


def _pending_buffer(ledger: CompanyLedger) -> Dict[str, Any]:
    """Lazy-init a pending-effects buffer piggy-backing on the ledger object.

    Structure:
        {
            'revenue_mult_next_week': 1.0,
            'margin_delta_pts_next_week': 0.0,
            'nps_delta_next_week': 0.0,
            'sla_delta_pts_next_week': 0.0,
            'capex_amortisation_weeks_remaining': [{amount, weeks}...],
        }
    """
    if not hasattr(ledger, "_pending"):
        object.__setattr__(ledger, "_pending", {
            "revenue_mult_next_week": 1.0,
            "margin_delta_pts_next_week": 0.0,
            "nps_delta_next_week": 0.0,
            "sla_delta_pts_next_week": 0.0,
            "weekly_opex_bump_inr": 0.0,
            "campaigns_running": [],
            "capex_projects": [],
        })
    return ledger._pending  # type: ignore[attr-defined]


def execute_approved_proposals(
    ledger: CompanyLedger,
    proposals: List[Proposal],
    decisions: List[ProposalDecision],
    rng: random.Random,
    week: int = 0,
    multi_year: bool = False,
) -> Dict[str, Any]:
    """Apply cash / inventory / NPS / revenue-multiplier effects of approved or modified proposals.

    Rejected and request_info verdicts are no-ops here; approved / modified
    proposals mutate cash, inventory, and pending effects.

    Returns a telemetry dict:
        {
            applied_cost_inr:   ₹ cash impact (signed; negative = spend),
            inventory_added:    {sku_id: qty} from po.place/po.bulk_deal,
            proposals_applied:  count of approvals + modifies actually executed,
            notes:              list of per-proposal strings for debugging / journaling,
        }
    """
    buf = _pending_buffer(ledger)
    applied_cost = 0.0
    inventory_added: Dict[str, float] = {}
    proposals_applied = 0
    unknown_sku_dropped = 0
    notes: List[str] = []

    decisions_by_id = {d.proposal_id: d for d in decisions}

    for prop in proposals:
        dec = decisions_by_id.get(prop.proposal_id)
        if dec is None or dec.verdict not in ("approve", "modify"):
            continue

        params = dict(prop.params)
        if dec.verdict == "modify" and dec.modified_params:
            params.update(dec.modified_params)

        effect_cost = 0.0  # signed ₹ this proposal costs/saves this week
        note = ""

        # --- Supply chain ---
        if prop.action == "po.place" or prop.action == "po.bulk_deal":
            sku_id = params.get("sku_id")
            qty = float(params.get("qty", 0))
            unit_cost = float(params.get("unit_cost", 0)) * ledger.cogs_factor
            if prop.action == "po.bulk_deal":
                disc = float(params.get("discount_pct", 0)) / 100.0
                unit_cost *= (1.0 - disc)
            total_cost = qty * unit_cost
            if sku_id not in ledger.sku_catalogue:
                # CEO modify (or upstream LLM) supplied an unknown sku_id. Charge
                # the cash to penalise approving nonsense, but skip the inventory
                # mutation so we don't seed a phantom row.
                effect_cost = -total_cost
                unknown_sku_dropped += 1
                note = f"PO {prop.action}: unknown sku_id={sku_id!r} — cash charged, no inventory effect"
            else:
                effect_cost = -total_cost
                inv = ledger.inventory.setdefault(sku_id, {"qty": 0.0, "value_inr": 0.0, "avg_age_days": 0.0})
                # Weighted-average age update
                old_qty = inv["qty"]
                inv["qty"] = old_qty + qty
                new_age = (inv["avg_age_days"] * old_qty + 0.0 * qty) / max(inv["qty"], 1e-6)
                inv["avg_age_days"] = new_age
                inv["value_inr"] = inv["qty"] * ledger.sku_catalogue[sku_id]["cost_inr"]
                inventory_added[sku_id] = inventory_added.get(sku_id, 0.0) + qty
                note = f"PO {prop.action}: +{qty:.0f} × {sku_id} at ₹{unit_cost:.1f} = ₹{total_cost:,.0f}"

        elif prop.action == "vendor.switch":
            # For simplicity treat as no immediate cash but flag a margin delta
            cost_delta_pct = float(params.get("cost_delta_pct", 0))
            buf["margin_delta_pts_next_week"] -= cost_delta_pct * 0.2  # rough pass-through
            note = f"Vendor switch: cost Δ={cost_delta_pct:+.1f}% → margin drag"

        elif prop.action == "safety_stock.adjust":
            # Pure policy; no immediate cash
            note = f"Safety stock {params.get('category')}: {params.get('pct_delta', 0):+}%"

        elif prop.action == "wastage.writeoff":
            sku_id = params.get("sku_id")
            qty = float(params.get("qty", 0))
            inv = ledger.inventory.get(sku_id)
            sku = ledger.sku_catalogue.get(sku_id) if sku_id else None
            if inv and sku:
                burn = min(inv["qty"], qty)
                inv["qty"] -= burn
                inv["value_inr"] = inv["qty"] * sku["cost_inr"]
                effect_cost = -burn * sku["cost_inr"] * 0.1  # 10% disposal cost
                note = f"Wastage writeoff: -{burn:.0f} × {sku_id}"
            else:
                if sku_id and sku is None:
                    unknown_sku_dropped += 1
                note = f"Wastage writeoff: sku_id={sku_id!r} not in catalogue or no inventory — skipped"

        # --- Store ops ---
        elif prop.action == "staff.schedule":
            delta_hours = float(params.get("delta_hours", 0))
            payroll_cost = delta_hours * 80.0  # ₹80/hr
            effect_cost = -payroll_cost
            buf["nps_delta_next_week"] += 0.3 * (1 if delta_hours > 0 else -1)
            note = f"Staff schedule: Δhours={delta_hours:+.0f} ₹{payroll_cost:,.0f}"

        elif prop.action == "local_promo.run":
            discount = float(params.get("discount_pct", 0))
            g = ledger.growth_lever_mult
            buf["revenue_mult_next_week"] *= (1.0 + 0.15 * discount / 10.0 * g)
            buf["margin_delta_pts_next_week"] -= discount * 0.5
            note = f"Local promo: {discount}% off"

        elif prop.action == "planogram.update":
            buf["revenue_mult_next_week"] *= 1.01
            note = "Planogram tweak (+1% revenue next week)"

        elif prop.action == "return.approve":
            refund = float(params.get("refund_inr", 0))
            effect_cost = -refund
            note = f"Return approved: -₹{refund:,.0f}"

        elif prop.action == "hours.extend":
            extra_hours = float(params.get("hours", 0))
            buf["revenue_mult_next_week"] *= (1.0 + 0.005 * extra_hours)
            effect_cost = -extra_hours * 60.0  # utility cost
            note = f"Hours extended: +{extra_hours}h"

        # --- Finance ---
        elif prop.action == "budget.reallocate":
            amt = float(params.get("amount_inr", 0))
            note = f"Budget reallocated ₹{amt:,.0f} ({params.get('from_dept')}→{params.get('to_dept')})"

        elif prop.action == "capex.approve":
            amt = float(params.get("amount_inr", 0))
            effect_cost = -amt
            payback_weeks = max(1, int(params.get("payback_weeks", 24) or 24))
            # Amortised revenue uplift: a project returns a fixed weekly revenue
            # bump for `payback_weeks` weeks. Faster payback => bigger weekly
            # bump => the uplift lands inside the episode and clears its cost;
            # slow payback => most of the return falls beyond the horizon =>
            # net negative. This turns capex from a pure-cost trap into a real
            # fast-vs-slow judgement call. Weekly bump ~= amt / payback * uplift.
            weekly_gain = (amt / payback_weeks) * E.CAPEX_PAYBACK_UPLIFT
            buf["capex_projects"].append(
                {"weekly_gain_inr": weekly_gain, "weeks_remaining": payback_weeks}
            )
            note = (
                f"CapEx: -₹{amt:,.0f} ({params.get('project_id', 'unknown')}, "
                f"payback {payback_weeks}w, +₹{weekly_gain:,.0f}/wk)"
            )

        elif prop.action == "price.guardrail_change":
            delta = float(params.get("min_margin_delta_pts", 0))
            buf["margin_delta_pts_next_week"] += delta
            note = f"Margin guardrail Δ{delta:+.1f}pt"

        elif prop.action == "line_of_credit.draw":
            amt = float(params.get("amount_inr", 0))
            avail = ledger.line_of_credit_limit - ledger.line_of_credit_drawn
            draw = min(amt, avail)
            ledger.cash_inr += draw
            ledger.line_of_credit_drawn += draw
            note = f"LoC draw ₹{draw:,.0f} (debt ₹{ledger.line_of_credit_drawn:,.0f}/{ledger.line_of_credit_limit:,.0f})"

        elif prop.action == "investor_report.flag":
            note = f"Investor flag: {params.get('metric', '?')}={params.get('value', '?')}"

        # --- Growth ---
        elif prop.action == "campaign.launch":
            spend = float(params.get("spend_inr", 0))
            effect_cost = -spend
            g = ledger.growth_lever_mult
            # Effect sized so a well-timed (festival) campaign clears its cost:
            # base_effect on ~₹5Cr/wk revenue must beat `spend`. At the old cap
            # (min 0.20, spend/3e7) even festival campaigns were ~break-even;
            # raising the divisor floor and cap makes timing a real +EV lever.
            base_effect = min(0.35, spend / 1.5e7) * g
            festival_synergy = _festival_synergy_mult(week, multi_year)
            buf["revenue_mult_next_week"] *= (1.0 + base_effect * festival_synergy)
            buf["campaigns_running"].append({"spend": spend, "weeks_remaining": 2})
            if festival_synergy > 1.0:
                note = f"Campaign launched ₹{spend:,.0f} (FESTIVAL SYNERGY {festival_synergy:.1f}x)"
            else:
                note = f"Campaign launched ₹{spend:,.0f}"

        elif prop.action == "loyalty.update":
            cost = float(params.get("perk_cost_inr", 0))
            effect_cost = -cost
            g = ledger.growth_lever_mult
            buf["nps_delta_next_week"] += 0.8 * g
            note = f"Loyalty perk ₹{cost:,.0f}"

        elif prop.action == "discount.run":
            depth = float(params.get("depth_pct", 0))
            g = ledger.growth_lever_mult
            buf["revenue_mult_next_week"] *= (1.0 + 0.12 * depth / 10.0 * g)
            buf["margin_delta_pts_next_week"] -= depth * 0.6
            note = f"Discount {depth}%"

        elif prop.action == "competitor.match":
            buf["margin_delta_pts_next_week"] -= 0.3
            note = "Competitor price match (-0.3pt margin)"

        elif prop.action == "brand.ambassador":
            cost = float(params.get("cost_inr", 0))
            effect_cost = -cost
            g = ledger.growth_lever_mult
            buf["nps_delta_next_week"] += 1.5 * g
            note = f"Brand ambassador ₹{cost:,.0f}"

        elif prop.action == "strategic.opportunity":
            cost = float(params.get("cost_inr", 0))
            effect_cost = -cost
            g = ledger.growth_lever_mult
            rev_mult = float(params.get("projected_revenue_mult", 1.15))
            duration = int(params.get("duration_weeks", 4))
            effective_mult = 1.0 + (rev_mult - 1.0) * g
            buf["revenue_mult_next_week"] *= effective_mult
            buf["nps_delta_next_week"] += 2.0 * g
            buf["campaigns_running"].append({"spend": cost, "weeks_remaining": duration})
            note = (
                f"STRATEGIC OPP: {params.get('name', '?')} ₹{cost:,.0f} "
                f"(rev +{(effective_mult-1)*100:.0f}% × {duration}wk)"
            )

        # --- Expansion ---
        elif prop.action == "city.enter":
            capex = float(params.get("estimated_capex_inr", 0))
            effect_cost = -capex
            note = f"City entry {params.get('city')} (CapEx -₹{capex:,.0f})"

        elif prop.action == "franchise.onboard":
            onboarding_cost = float(params.get("onboarding_cost_inr", 0))
            effect_cost = -onboarding_cost
            # Add franchise slot
            if "candidate_id" in params and "city" in params:
                new_fid = f"F{len(ledger.franchisees)+1:03d}"
                ledger.franchisees.append({
                    "franchise_id": new_fid,
                    "store_id": f"S_NEW_{new_fid}",
                    "city": params["city"],
                    "health_score": round(rng.uniform(0.55, 0.90), 2),
                    "complaints_open": 0,
                })
            note = f"Franchise onboarded in {params.get('city', '?')}"

        elif prop.action == "franchise.review":
            fid = params.get("franchise_id")
            action = params.get("action", "warn")
            for fr in ledger.franchisees:
                if fr["franchise_id"] == fid:
                    if action == "reward":
                        fr["health_score"] = min(1.0, fr["health_score"] + 0.1)
                    elif action == "penalise":
                        fr["health_score"] = max(0.0, fr["health_score"] - 0.1)
                    break
            note = f"Franchise {fid}: {action}"

        elif prop.action == "location.score":
            note = f"Location scored {params.get('city', '?')}/{params.get('zone', '?')}"

        elif prop.action == "franchise.exit":
            fid = params.get("franchise_id")
            ledger.franchisees = [f for f in ledger.franchisees if f["franchise_id"] != fid]
            note = f"Franchise exit: {fid}"

        else:
            note = f"Unknown action {prop.action} (no effect)"

        # Immediate cash impact
        ledger.cash_inr += effect_cost
        applied_cost += effect_cost
        proposals_applied += 1
        # Route opex-bearing spends to EBITDA. Capitalized spends (PO,
        # wastage writeoff) are intentionally excluded — they flow through
        # COGS as inventory sells / spoils.
        if prop.action in OPEX_BEARING_ACTIONS and effect_cost < 0:
            ledger.pnl_qtd.opex_qtd_inr += -effect_cost
        notes.append(f"[{prop.proposal_id}/{dec.verdict}] {note}")

    return {
        "applied_cost_inr": applied_cost,
        "inventory_added": inventory_added,
        "proposals_applied": proposals_applied,
        "unknown_sku_dropped": unknown_sku_dropped,
        "notes": notes,
    }


def consume_pending_effects(ledger: CompanyLedger) -> Dict[str, float]:
    """Pop the pending-effects buffer at the start of a new week and return the effects to apply.

    After consumption, the buffer resets to neutral defaults (ready to accumulate
    effects from next week's approvals).
    """
    buf = _pending_buffer(ledger)
    effects = {
        "revenue_mult": buf["revenue_mult_next_week"],
        "margin_delta_pts": buf["margin_delta_pts_next_week"],
        "nps_delta": buf["nps_delta_next_week"],
        "sla_delta_pts": buf["sla_delta_pts_next_week"],
        "weekly_opex_bump_inr": buf["weekly_opex_bump_inr"],
    }
    # Pay out amortised capex returns as high-margin revenue (flows to EBITDA
    # and cash). Each project pays weekly_gain_inr for weeks_remaining weeks.
    capex_gain = 0.0
    capex_still = []
    for proj in buf.get("capex_projects", []):
        if proj["weeks_remaining"] > 0:
            capex_gain += proj["weekly_gain_inr"]
            proj["weeks_remaining"] -= 1
            if proj["weeks_remaining"] > 0:
                capex_still.append(proj)
    if capex_gain > 0:
        # Treat as near-pure-margin return (10% COGS) so it lifts EBITDA.
        settle_revenue(ledger, capex_gain, capex_gain * 0.10)
    buf["capex_projects"] = capex_still

    # Tick campaign durations
    still_running = []
    for c in buf["campaigns_running"]:
        c["weeks_remaining"] -= 1
        if c["weeks_remaining"] > 0:
            still_running.append(c)
    # Reset buffer
    buf["revenue_mult_next_week"] = 1.0 + 0.05 * len(still_running)  # legacy carryover
    buf["margin_delta_pts_next_week"] = 0.0
    buf["nps_delta_next_week"] = 0.0
    buf["sla_delta_pts_next_week"] = 0.0
    buf["weekly_opex_bump_inr"] = 0.0
    buf["campaigns_running"] = still_running
    return effects


# ---------------------------------------------------------------------------
# Weekly KPI snapshot
# ---------------------------------------------------------------------------

def snapshot_weekly_kpis(
    ledger: CompanyLedger,
    weekly_revenue: float,
    weekly_cogs: float,
    weekly_stockout_rate_pct: float,
    weekly_shrinkage_pct: float,
    weekly_sla_hit_rate_pct: float,
    weekly_nps: float,
    weekly_basket_inr: float,
    weekly_footfall_per_store: float,
    weekly_repeat_purchase_pct: float,
) -> KPISnapshot:
    """Compute this week's KPI snapshot and deltas vs prior week.

    Appends to `ledger.kpi_history` (capped at 13 entries). Returns the snap.
    """
    margin_pct = (
        (weekly_revenue - weekly_cogs) / weekly_revenue * 100.0
        if weekly_revenue > 0
        else 0.0
    )

    snap = KPISnapshot(
        revenue_inr=weekly_revenue,
        gross_margin_pct=margin_pct,
        stockout_rate_pct=weekly_stockout_rate_pct,
        nps=weekly_nps,
        cash_inr=ledger.cash_inr,
        shrinkage_pct=weekly_shrinkage_pct,
        delivery_sla_hit_rate_pct=weekly_sla_hit_rate_pct,
        basket_size_inr=weekly_basket_inr,
        footfall_per_store=weekly_footfall_per_store,
        repeat_purchase_rate_pct=weekly_repeat_purchase_pct,
    )

    if ledger.kpi_history:
        prev = ledger.kpi_history[-1]
        if prev.revenue_inr > 0:
            snap.revenue_delta_pct = (snap.revenue_inr - prev.revenue_inr) / prev.revenue_inr * 100.0
        snap.margin_delta_pts = snap.gross_margin_pct - prev.gross_margin_pct
        snap.stockout_delta_pts = snap.stockout_rate_pct - prev.stockout_rate_pct
        snap.nps_delta = snap.nps - prev.nps
        snap.sla_delta_pts = snap.delivery_sla_hit_rate_pct - prev.delivery_sla_hit_rate_pct
        snap.cash_delta_inr = snap.cash_inr - prev.cash_inr
        snap.cash_burn_rate_inr_per_week = _rolling_cash_burn_rate(
            ledger, snap.cash_delta_inr
        )
        if snap.cash_burn_rate_inr_per_week > 0:
            snap.cash_runway_weeks = max(0.0, snap.cash_inr) / snap.cash_burn_rate_inr_per_week
        snap.cash_pressure_score = _cash_pressure_score(
            cash_inr=snap.cash_inr,
            burn_rate_inr=snap.cash_burn_rate_inr_per_week,
            runway_weeks=snap.cash_runway_weeks,
        )
        is_pressure_week = _is_cash_pressure_week(
            burn_rate_inr=snap.cash_burn_rate_inr_per_week,
            runway_weeks=snap.cash_runway_weeks,
        )
        snap.cash_pressure_streak_weeks = (
            prev.cash_pressure_streak_weeks + 1 if is_pressure_week else 0
        )
        if snap.cash_pressure_streak_weeks >= E.CASH_PRESSURE_PERSISTENCE_WEEKS:
            snap.cash_pressure_score = max(snap.cash_pressure_score, 0.5)

    ledger.kpi_history.append(snap)
    if len(ledger.kpi_history) > E.DEFAULT_WEEKS_PER_QUARTER:
        ledger.kpi_history = ledger.kpi_history[-E.DEFAULT_WEEKS_PER_QUARTER:]

    return snap


def _rolling_cash_burn_rate(ledger: CompanyLedger, current_cash_delta_inr: float) -> float:
    """Average weekly cash outflow over the recent lookback window.

    ``cash_delta_inr`` remains the current week's net cash movement. Burn rate is
    intentionally smoother: it treats positive weeks as zero burn and averages
    recent weekly outflows, so a quiet week does not erase the runway signal.
    """
    lookback_weeks = max(1, E.CASH_BURN_LOOKBACK_WEEKS)
    previous_week_deltas = [snap.cash_delta_inr for snap in ledger.kpi_history[1:]]
    deltas = (previous_week_deltas + [current_cash_delta_inr])[-lookback_weeks:]
    if not deltas:
        return 0.0
    return sum(max(0.0, -delta) for delta in deltas) / len(deltas)


def _is_cash_pressure_week(burn_rate_inr: float, runway_weeks: float | None) -> bool:
    warn_burn = E.STARTING_CASH_INR * E.CASH_BURN_WARN_PCT_OF_STARTING_CASH
    return burn_rate_inr >= warn_burn or (
        runway_weeks is not None and runway_weeks <= E.CASH_RUNWAY_WARN_WEEKS
    )


def _cash_pressure_score(
    *,
    cash_inr: float,
    burn_rate_inr: float,
    runway_weeks: float | None,
) -> float:
    """Map cash position into a [0, 1] warning (burn rate + runway + deep shortfall).

    Previously included a `cash_shortfall_score` that fired whenever cash <
    starting balance. That penalised normal operations (any inventory spend
    dipped cash below starting) and dominated the score even when runway was
    fine. Now the shortfall term only kicks in below 50% of starting cash —
    actual liquidity stress, not just having spent some money.
    """
    half_start = E.STARTING_CASH_INR * 0.5
    cash_shortfall_score = _clip01((half_start - cash_inr) / max(1.0, half_start))

    warn_burn = E.STARTING_CASH_INR * E.CASH_BURN_WARN_PCT_OF_STARTING_CASH
    critical_burn = E.STARTING_CASH_INR * E.CASH_BURN_CRITICAL_PCT_OF_STARTING_CASH
    burn_score = _clip01((burn_rate_inr - warn_burn) / max(1.0, critical_burn - warn_burn))

    runway_score = 0.0
    if runway_weeks is not None:
        runway_score = _clip01((E.CASH_RUNWAY_WARN_WEEKS - runway_weeks) / E.CASH_RUNWAY_WARN_WEEKS)

    return max(cash_shortfall_score, burn_score, runway_score)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# High-level tick
# ---------------------------------------------------------------------------

def tick_one_day(
    ledger: CompanyLedger,
    day_of_quarter: int,
    category_demand_units: Dict[str, float],
    sla_hit_rate_pct: float,
    crisis_extra_opex_inr: float,
    rng: random.Random,
    cogs_mult_by_category: Optional[Dict[str, float]] = None,
    payment_friction_pct: float = 0.0,
) -> Dict[str, Any]:
    """Run one simulated day.

    Returns a telemetry dict with all the raw daily numbers the caller needs
    to assemble weekly KPIs.
    """
    sales = sell_daily_demand(ledger, category_demand_units, rng)

    if cogs_mult_by_category:
        extra_cogs = 0.0
        for sku_id, qty in sales.get("units_sold", {}).items():
            sku = ledger.sku_catalogue.get(sku_id)
            if sku and qty > 0:
                cat = sku["category"]
                mult = cogs_mult_by_category.get(cat, 1.0)
                if mult != 1.0:
                    extra_cogs += qty * sku["cost_inr"] * (mult - 1.0)
        sales["cogs_inr"] += extra_cogs
        ledger.cash_inr -= extra_cogs

    if payment_friction_pct > 0:
        sales["revenue_inr"] *= (1.0 - payment_friction_pct)

    loss = apply_shrinkage_and_spoilage(ledger, rng)
    opex_applied = apply_daily_overhead(ledger, extra_inr=crisis_extra_opex_inr)

    settle_revenue(ledger, sales["revenue_inr"], sales["cogs_inr"])
    settle_opex(ledger, opex_applied)

    return {
        "day_of_quarter": day_of_quarter,
        "revenue_inr": sales["revenue_inr"],
        "cogs_inr": sales["cogs_inr"],
        "opex_inr": opex_applied,
        "units_sold": sales["units_sold"],
        "units_queried": sales["units_queried"],
        "stockout_units": sales["stockout_units"],
        "stockout_rate_pct": sales["stockout_rate_pct"],
        "shrinkage_value_inr": loss["shrinkage_value_inr"],
        "spoilage_value_inr": loss["spoilage_value_inr"],
        "sla_hit_rate_pct": sla_hit_rate_pct,
    }
