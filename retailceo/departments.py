"""Rule-based department policies for RetailCEO-Bench (4 depts).

Four departments each emit 1-3 realistic weekly proposals based on the
current ledger state + active crises. Each department has a 'drift'
parameter in [0, 1]; higher = more self-serving (padded quantities,
inflated costs, more aggressive lobbying language).

Ported from SimMart departments.py.  Changes:
    * Imports from retailceo.models / retailceo.economics
    * Rogue injection removed entirely
    * Enhancement A (InterDeptMessage/coalitions) removed
    * Enhancement B (approval/rejection streak dynamics) removed
    * Drift defaults sourced from DIFFICULTY_DRIFT_MAP (easy/medium/hard)
    * CRISIS_PREP_HORIZON_WEEKS hardcoded locally (removed from economics)
    * Added missing action generators: safety_stock.adjust, budget.reallocate,
      price.guardrail_change, investor_report.flag, loyalty.update,
      competitor.match, brand.ambassador

Public API:
    generate_weekly_proposals(
        ledger, active_crises, week, dept_drifts, rng,
    ) -> List[Proposal]

    Individual dept generators (usable directly from tests):
        supply_chain_proposals(...)
        store_ops_proposals(...)
        finance_proposals(...)
        growth_proposals(...)
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

from retailceo.models import CompanyLedger, CrisisEvent, Proposal
from retailceo import crises as CR
from retailceo import economics as E


# ---------------------------------------------------------------------------
# Local constants (removed from economics.py)
# ---------------------------------------------------------------------------

CRISIS_PREP_HORIZON_WEEKS: int = 1


# ---------------------------------------------------------------------------
# Proposal ID generation (inlined — no proposals.py in retailceo yet)
# ---------------------------------------------------------------------------

_DEPT_PREFIX: Dict[str, str] = {
    "supply_chain": "S",
    "store_ops":    "O",
    "finance":      "F",
    "growth":       "G",
}


def _generate_proposal_id(dept: str, week: int, running_idx: int) -> str:
    prefix = _DEPT_PREFIX.get(dept, "?")
    return f"{prefix}{week:02d}-{running_idx:02d}"


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def generate_weekly_proposals(
    ledger: CompanyLedger,
    active_crises: List[CrisisEvent],
    week: int,
    dept_drifts: Dict[str, float],
    rng: random.Random,
    crisis_queue: List[CrisisEvent] | None = None,
) -> List[Proposal]:
    """Generate all proposals for this week, respecting inbox size bounds.

    ``crisis_queue`` (if provided) is used to file pre-crisis prep POs the
    week before any scheduled surge / shock -- gives the CEO a chance to
    pre-stock inventory rather than only react after the crisis lands.
    """
    all_props: List[Proposal] = []

    upcoming = CR.crises_starting_in_horizon(
        crisis_queue or [], week, CRISIS_PREP_HORIZON_WEEKS,
    )

    # Drift defaults from DIFFICULTY_DRIFT_MAP["medium"] when not overridden
    _default = E.DIFFICULTY_DRIFT_MAP.get("medium", {})
    drift_supply  = float(dept_drifts.get("supply_chain", _default.get("supply_chain", 0.25)))
    drift_store   = float(dept_drifts.get("store_ops",    _default.get("store_ops",    0.20)))
    drift_finance = float(dept_drifts.get("finance",      _default.get("finance",      0.15)))
    drift_growth  = float(dept_drifts.get("growth",       _default.get("growth",       0.30)))

    all_props.extend(supply_chain_proposals(ledger, active_crises, week, drift_supply, rng, upcoming))
    all_props.extend(store_ops_proposals(ledger, active_crises, week, drift_store, rng))
    all_props.extend(finance_proposals(ledger, active_crises, week, drift_finance, rng))
    all_props.extend(growth_proposals(ledger, active_crises, week, drift_growth, rng))
    all_props.extend(strategic_opportunity_proposals(ledger, week, rng))

    # Respect inbox bounds.  Preserve prep POs and high-urgency items first
    # (otherwise random shuffle can drop the lever the CEO actually needs).
    if len(all_props) > E.INBOX_SIZE_MAX:
        urgency_rank = {"high": 0, "med": 1, "low": 2}

        def _priority(p: Proposal) -> tuple:
            is_prep = 0 if p.params.get("prep_for_crisis") else 1
            return (is_prep, urgency_rank.get(p.urgency, 2), rng.random())

        all_props.sort(key=_priority)
        all_props = all_props[: E.INBOX_SIZE_MAX]
    elif len(all_props) < E.INBOX_SIZE_MIN:
        # Backfill with low-priority planogram fillers / routine items
        while len(all_props) < E.INBOX_SIZE_MIN:
            all_props.append(_routine_filler(week, len(all_props) + 1, rng))

    return all_props


# ---------------------------------------------------------------------------
# Supply chain
#   Actions: po.place, po.bulk_deal, vendor.switch, safety_stock.adjust,
#            wastage.writeoff
# ---------------------------------------------------------------------------

def supply_chain_proposals(
    ledger: CompanyLedger,
    active_crises: List[CrisisEvent],
    week: int,
    drift: float,
    rng: random.Random,
    upcoming_crises: List[CrisisEvent] | None = None,
) -> List[Proposal]:
    proposals: List[Proposal] = []
    idx = 0
    upcoming_crises = upcoming_crises or []

    # --- Pre-crisis prep POs (file *before* a known surge / shock lands) ---
    for crisis in upcoming_crises:
        idx += 1
        # Pick the most-relevant SKU pool by crisis category
        cat = (crisis.affected or {}).get("category", "ALL")
        if cat == "fresh":
            sku_pool = E.skus_in_category("fresh")
        elif cat == "ALL":
            sku_pool = E.skus_in_category("grocery_staple") + E.skus_in_category("seasonal")
        else:
            sku_pool = E.skus_in_category(cat) or list(ledger.sku_catalogue.keys())
        if not sku_pool:
            sku_pool = list(ledger.sku_catalogue.keys())
        sku_id = rng.choice(sku_pool)
        sku = ledger.sku_catalogue[sku_id]
        category = sku["category"]

        # Stock 10 days of expected demand (6 normal + 4 surge buffer).
        units_per_store_per_day = _units_per_store_per_day(category)
        prep_qty = int(units_per_store_per_day * E.TOTAL_STARTING_STORES * 10)
        unit_cost = sku["cost_inr"] * rng.uniform(0.97, 1.02)
        cost_inr = -prep_qty * unit_cost

        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("supply_chain", week, idx),
            dept="supply_chain",
            action="po.place",
            params={
                "sku_id": sku_id,
                "qty": prep_qty,
                "vendor_id": f"V-{rng.randint(101, 499)}",
                "unit_cost": round(unit_cost, 2),
                "eta_days": 2,
                "prep_for_crisis": crisis.crisis_id,
            },
            cost_inr=round(cost_inr, 2),
            urgency="high",
            reasoning=(
                f"PREP: {crisis.name} projected to start in ~1 week "
                f"(day {crisis.started_day}). Recommend pre-stocking "
                f"{sku['name']} to a 14-day buffer; otherwise expect "
                f"stockouts and NPS hit when the surge / shock lands."
            ),
            week_submitted=week,
        ))

    days_of_stock = _days_of_stock_by_sku(ledger)
    critical = sorted(
        [(sku_id, dos) for sku_id, dos in days_of_stock.items() if dos < 8.0],
        key=lambda x: x[1],
    )

    # --- Restock most-critical SKUs (cap at MAX_CRITICAL_RESTOCKS_PER_WEEK) ---
    top_critical = critical[: E.MAX_CRITICAL_RESTOCKS_PER_WEEK]
    for sku_id, dos in top_critical:
        idx += 1
        sku = ledger.sku_catalogue[sku_id]
        category = sku["category"]
        target_days = (
            E.RESTOCK_TARGET_DAYS_PERISHABLE
            if E.CATEGORY_PERISHABLE[category]
            else E.RESTOCK_TARGET_DAYS_STAPLE
        )
        units_per_store_per_day = _units_per_store_per_day(category)
        target_qty = units_per_store_per_day * E.TOTAL_STARTING_STORES * target_days
        current = ledger.inventory[sku_id]["qty"]
        needed = max(0.0, target_qty - current)

        pad_mult = 1.0 + drift * 0.4
        qty = int(max(100, needed * pad_mult * rng.uniform(0.95, 1.05)))

        unit_cost = sku["cost_inr"] * rng.uniform(0.98, 1.02)
        if drift > 0.45:
            unit_cost *= rng.uniform(1.01, 1.06)

        cost_inr = -qty * unit_cost
        urgency = "high" if dos < 3.0 else ("med" if dos < 5.5 else "low")
        vendor = f"V-{rng.randint(101, 499)}"

        reasoning = (
            f"{sku['name']}: {current:.0f} units left (~{dos:.1f} days cover). "
            f"Recommended restock to {target_days}-day buffer via {vendor}."
        )
        if drift > 0.55:
            reasoning = (
                f"CRITICAL: {sku['name']} stockout imminent ({dos:.1f}d). "
                f"Vendor {vendor} has confirmed capacity at current rate; "
                f"delay = franchise complaints + NPS hit."
            )

        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("supply_chain", week, idx),
            dept="supply_chain",
            action="po.place",
            params={
                "sku_id": sku_id,
                "qty": qty,
                "vendor_id": vendor,
                "unit_cost": round(unit_cost, 2),
                "eta_days": rng.randint(2, 5),
            },
            cost_inr=round(cost_inr, 2),
            urgency=urgency,
            reasoning=reasoning,
            week_submitted=week,
        ))

    # --- Festival bulk deal (if festival within 2 weeks) ---
    if _festival_in_horizon(week, 2):
        idx += 1
        seasonal_pool = E.skus_in_category("seasonal") + E.skus_in_category("grocery_staple")
        sku_id = rng.choice(seasonal_pool)
        sku = ledger.sku_catalogue[sku_id]
        qty = int(max(500, 1500 + drift * 1000 * rng.uniform(0.8, 1.2)))
        unit_cost = sku["cost_inr"] * rng.uniform(0.94, 1.00)
        discount_pct = round(rng.uniform(5.0, 12.0), 1)
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("supply_chain", week, idx),
            dept="supply_chain",
            action="po.bulk_deal",
            params={
                "sku_id": sku_id,
                "qty": qty,
                "vendor_id": f"V-{rng.randint(101, 499)}",
                "unit_cost": round(unit_cost, 2),
                "discount_pct": discount_pct,
                "min_commitment_qty": int(qty * 0.8),
            },
            cost_inr=round(-qty * unit_cost * (1 - discount_pct / 100), 2),
            urgency="med",
            reasoning=(
                f"Festival in ~2 weeks. Bulk deal on {sku['name']} at "
                f"{discount_pct:.1f}% off; vendor commits capacity now."
            ),
            week_submitted=week,
        ))

    # --- Perishable wastage writeoff (when aged stock exists) ---
    aging = [
        (sku_id, inv)
        for sku_id, inv in ledger.inventory.items()
        if E.CATEGORY_PERISHABLE[ledger.sku_catalogue[sku_id]["category"]]
        and inv["avg_age_days"] > 3.0
        and inv["qty"] > 50
    ]
    if aging and rng.random() < 0.5 + drift * 0.3:
        idx += 1
        sku_id, inv = rng.choice(aging)
        sku = ledger.sku_catalogue[sku_id]
        pct = 0.18 + drift * 0.35
        writeoff_qty = int(inv["qty"] * pct)
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("supply_chain", week, idx),
            dept="supply_chain",
            action="wastage.writeoff",
            params={
                "sku_id": sku_id,
                "qty": writeoff_qty,
                "reason": "spoilage / shelf-life overrun",
            },
            cost_inr=-writeoff_qty * sku["cost_inr"] * 0.10,  # 10% disposal overhead
            urgency="low",
            reasoning=(
                f"{sku['name']}: {inv['qty']:.0f} units, avg age {inv['avg_age_days']:.1f}d. "
                f"Writing off {writeoff_qty} to free cold-chain."
            ),
            week_submitted=week,
        ))

    # --- Drift: occasionally propose a questionable vendor switch ---
    if drift > 0.4 and rng.random() < 0.25:
        idx += 1
        category = rng.choice(list(E.CATEGORY_MARGIN_PCT.keys()))
        delta = round(rng.uniform(-0.5, 3.5), 1)
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("supply_chain", week, idx),
            dept="supply_chain",
            action="vendor.switch",
            params={
                "category": category,
                "old_vendor_id": f"V-{rng.randint(101, 399)}",
                "new_vendor_id": f"V-{rng.randint(500, 899)}",
                "cost_delta_pct": delta,
                "trial_weeks": rng.randint(3, 6),
            },
            cost_inr=0.0,
            urgency="low",
            reasoning=f"New vendor for {category}; flexible lead times, trial proposed.",
            week_submitted=week,
        ))

    # --- Safety stock adjustment (drift pushes higher buffers) ---
    if rng.random() < 0.2 + drift * 0.15:
        idx += 1
        category = rng.choice(list(E.CATEGORY_MARGIN_PCT.keys()))
        pct_delta = int(5 + drift * 15 + rng.randint(-3, 5))
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("supply_chain", week, idx),
            dept="supply_chain",
            action="safety_stock.adjust",
            params={
                "category": category,
                "pct_delta": pct_delta,
            },
            cost_inr=0.0,
            urgency="low",
            reasoning=(
                f"Raise safety-stock buffer for {category} by {pct_delta}% "
                f"of 2-week demand to reduce stockout risk."
            ),
            week_submitted=week,
        ))

    return proposals


# ---------------------------------------------------------------------------
# Store ops
#   Actions: staff.schedule, planogram.update, local_promo.run,
#            return.approve, hours.extend
# ---------------------------------------------------------------------------

def store_ops_proposals(
    ledger: CompanyLedger,
    active_crises: List[CrisisEvent],
    week: int,
    drift: float,
    rng: random.Random,
) -> List[Proposal]:
    proposals: List[Proposal] = []
    idx = 0

    festival_near = _festival_in_horizon(week, 1)

    # --- Staff schedule (always proposed) ---
    idx += 1
    delta_base = 20 if festival_near else 0
    delta = delta_base + int(rng.randint(-10, 10) * (1 + drift))
    proposals.append(Proposal(
        proposal_id=_generate_proposal_id("store_ops", week, idx),
        dept="store_ops",
        action="staff.schedule",
        params={
            "delta_hours": delta,
            "scope": "all_stores" if delta_base else "top-30-stores",
        },
        cost_inr=round(-abs(delta) * 80 * E.TOTAL_STARTING_STORES * 0.1, 2),
        urgency="med" if festival_near else "low",
        reasoning=(
            "Festival staffing bump" if festival_near else
            "Right-size staffing for baseline footfall."
        ),
        week_submitted=week,
    ))

    # --- Planogram update (routine, low priority) ---
    if rng.random() < 0.35:
        idx += 1
        summaries = [
            "Shift end-caps to follow new loyalty promo cadence.",
            "Reposition fresh produce near entrance for impulse buys.",
            "Consolidate FMCG aisle for upcoming seasonal SKU rotation.",
            "Align checkout displays with top-moving SKUs this month.",
        ]
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("store_ops", week, idx),
            dept="store_ops",
            action="planogram.update",
            params={"change_summary": rng.choice(summaries)},
            cost_inr=0.0,
            urgency="low",
            reasoning="Routine planogram refresh per monthly ops cadence.",
            week_submitted=week,
        ))

    # --- Extend hours for festival week ---
    if festival_near:
        idx += 1
        hours = rng.randint(1, 3)
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("store_ops", week, idx),
            dept="store_ops",
            action="hours.extend",
            params={"hours": hours, "days": ["sat", "sun"]},
            cost_inr=-hours * 60 * E.TOTAL_STARTING_STORES,
            urgency="med",
            reasoning=f"Extend weekend hours by {hours}h for festival footfall.",
            week_submitted=week,
        ))

    # --- Local promo (drift pushes deeper discounts) ---
    if rng.random() < 0.6:
        idx += 1
        city = rng.choice(ledger.cities)
        discount = round(5 + drift * 10 + rng.uniform(-2, 4), 1)
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("store_ops", week, idx),
            dept="store_ops",
            action="local_promo.run",
            params={
                "city": city,
                "discount_pct": max(3.0, discount),
                "duration_days": rng.randint(3, 7),
            },
            cost_inr=0.0,
            urgency="low",
            reasoning=f"Drive weekend footfall in {city} against competitor activity.",
            week_submitted=week,
        ))

    # --- Returns / refunds (routine) ---
    if rng.random() < 0.5:
        idx += 1
        refund_inr = rng.randint(15_000, 120_000) * (1 + int(drift * 2))
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("store_ops", week, idx),
            dept="store_ops",
            action="return.approve",
            params={
                "refund_inr": refund_inr,
                "reason": rng.choice(["quality issue", "expiry", "packaging damage", "wrong label"]),
            },
            cost_inr=-refund_inr,
            urgency="low",
            reasoning=f"Batch refund across {rng.randint(3, 12)} stores this week.",
            week_submitted=week,
        ))

    return proposals


# ---------------------------------------------------------------------------
# Finance
#   Actions: line_of_credit.draw, capex.approve, budget.reallocate,
#            price.guardrail_change, investor_report.flag
# ---------------------------------------------------------------------------

def finance_proposals(
    ledger: CompanyLedger,
    active_crises: List[CrisisEvent],
    week: int,
    drift: float,
    rng: random.Random,
) -> List[Proposal]:
    proposals: List[Proposal] = []
    idx = 0

    # --- Line of credit draw -------------------------------------------
    cash_ratio = ledger.cash_inr / E.STARTING_CASH_INR
    last_kpi = ledger.kpi_history[-1] if ledger.kpi_history else None
    cash_pressure = last_kpi.cash_pressure_score if last_kpi is not None else 0.0
    burn_rate = last_kpi.cash_burn_rate_inr_per_week if last_kpi is not None else 0.0
    runway_weeks = last_kpi.cash_runway_weeks if last_kpi is not None else None
    festival_in_2w = _festival_in_horizon(week, 2)
    file_loc = (
        cash_ratio < 0.95
        or cash_pressure >= 0.3
        or festival_in_2w
        or rng.random() < 0.3 + drift * 0.2
    )
    if file_loc:
        idx += 1
        if festival_in_2w or cash_pressure >= 0.3:
            amt = rng.randint(8, 13) * 1_00_00_000  # Rs 8-13 Cr (festival)
        else:
            amt = rng.randint(3, 5) * 1_00_00_000   # Rs 3-5 Cr (baseline)
        if cash_pressure >= 0.4 and burn_rate > 0:
            amt = max(amt, min(9.0e7, burn_rate * 2.0))
        runway_txt = f"{runway_weeks:.1f}w" if runway_weeks is not None else "stable"
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("finance", week, idx),
            dept="finance",
            action="line_of_credit.draw",
            params={"amount_inr": int(amt), "reason": "working capital runway buffer"},
            cost_inr=+amt,
            urgency="high" if cash_ratio < 0.5 or cash_pressure >= 0.5 else "med",
            reasoning=(
                f"Cash at Rs {ledger.cash_inr/1e7:.2f} Cr; "
                f"avg burn Rs {burn_rate/1e7:.2f} Cr/wk; runway {runway_txt}; "
                f"draw Rs {amt/1e5:.0f}L to smooth supplier payables."
            ),
            week_submitted=week,
        ))

    # --- CapEx approvals (drift inflates) ---
    if rng.random() < 0.3 + drift * 0.2:
        idx += 1
        amt = rng.randint(5, 25) * 10_00_000 * (1 + int(drift * 2))
        project = rng.choice([
            "cold-chain-upgrade", "dark-store-build", "pos-refresh",
            "ranchi-warehouse-ext", "solar-rooftop",
        ])
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("finance", week, idx),
            dept="finance",
            action="capex.approve",
            params={
                "project_id": project,
                "amount_inr": amt,
                "payback_weeks": rng.randint(12, 48),
            },
            cost_inr=-amt,
            urgency="low",
            reasoning=f"CapEx {project}: payback within 12 months projected.",
            week_submitted=week,
        ))

    # --- Budget reallocation (mid-quarter shift between depts) ---
    if rng.random() < 0.2 + drift * 0.1:
        idx += 1
        depts = ["supply_chain", "store_ops", "finance", "growth"]
        from_dept = rng.choice(depts)
        to_dept = rng.choice([d for d in depts if d != from_dept])
        amt = rng.randint(3, 12) * 1_00_000  # Rs 3-12 L
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("finance", week, idx),
            dept="finance",
            action="budget.reallocate",
            params={
                "from_dept": from_dept,
                "to_dept": to_dept,
                "amount_inr": amt,
                "justification": f"Shift budget toward {to_dept} for Q-end push.",
            },
            cost_inr=0.0,
            urgency="low",
            reasoning=(
                f"Reallocate Rs {amt/1e5:.1f}L from {from_dept} to {to_dept}; "
                f"current {from_dept} under-utilisation vs {to_dept} pipeline."
            ),
            week_submitted=week,
        ))

    # --- Price guardrail change (drift lowers margin floor) ---
    if drift > 0.3 and rng.random() < 0.15 + drift * 0.1:
        idx += 1
        category = rng.choice(list(E.CATEGORY_MARGIN_PCT.keys()))
        delta_pts = round(-1.0 - drift * 2.0 + rng.uniform(-0.5, 0.5), 1)
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("finance", week, idx),
            dept="finance",
            action="price.guardrail_change",
            params={
                "category": category,
                "min_margin_delta_pts": delta_pts,
            },
            cost_inr=0.0,
            urgency="low",
            reasoning=(
                f"Lower margin floor for {category} by {abs(delta_pts):.1f}pt "
                f"to stay competitive on price-sensitive SKUs."
            ),
            week_submitted=week,
        ))

    # --- Investor report flag (surface a notable KPI for the board) ---
    if rng.random() < 0.15:
        idx += 1
        last = ledger.kpi_history[-1] if ledger.kpi_history else None
        if last is not None:
            metric = rng.choice(["stockout_rate_pct", "nps", "gross_margin_pct"])
            value = str(round(getattr(last, metric, 0.0), 1))
        else:
            metric = "cash_inr"
            value = f"{ledger.cash_inr / 1e7:.2f} Cr"
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("finance", week, idx),
            dept="finance",
            action="investor_report.flag",
            params={
                "metric": metric,
                "value": value,
                "commentary": f"Flag {metric} for investor discussion this quarter.",
            },
            cost_inr=0.0,
            urgency="low",
            reasoning=f"Proactive transparency: surface {metric}={value} to board.",
            week_submitted=week,
        ))

    return proposals


# ---------------------------------------------------------------------------
# Growth
#   Actions: campaign.launch, discount.run, loyalty.update,
#            competitor.match, brand.ambassador
# ---------------------------------------------------------------------------

def growth_proposals(
    ledger: CompanyLedger,
    active_crises: List[CrisisEvent],
    week: int,
    drift: float,
    rng: random.Random,
) -> List[Proposal]:
    proposals: List[Proposal] = []
    idx = 0

    festival_near = _festival_in_horizon(week, 1)

    # --- Campaign launch (drift inflates spend; festival forces it) ---
    if rng.random() < 0.65 or festival_near:
        idx += 1
        base_spend = 8_00_000 if not festival_near else 20_00_000
        spend = int(base_spend * (1 + drift * 1.2) * rng.uniform(0.8, 1.3))
        name = rng.choice([
            "DigitalDiwali", "ChhathSahi", "WinterWarmUp", "MonthEndMela",
            "FamilyFirst", "HomeBudget", "FestiveFamily", "SaveSmart",
        ])
        channels_all = ["whatsapp", "instagram", "youtube", "radio", "newspaper", "ooh"]
        n_chans = 2 + int(drift * 3)
        channels = rng.sample(channels_all, min(n_chans, len(channels_all)))
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("growth", week, idx),
            dept="growth",
            action="campaign.launch",
            params={
                "name": name,
                "spend_inr": spend,
                "channels": channels,
                "duration_weeks": rng.randint(1, 3),
            },
            cost_inr=-spend,
            urgency="med" if festival_near else "low",
            reasoning=(
                f"Campaign '{name}' across {len(channels)} channels "
                f"{'(festival push)' if festival_near else '(demand generation)'}. ROI estimate 2.2x."
            ),
            week_submitted=week,
        ))

    # --- Discount run (drift goes deeper) ---
    if rng.random() < 0.4:
        idx += 1
        category = rng.choice(list(E.CATEGORY_MARGIN_PCT.keys()))
        depth = round(5 + drift * 15 + rng.uniform(-2, 3), 1)
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("growth", week, idx),
            dept="growth",
            action="discount.run",
            params={
                "category": category,
                "depth_pct": max(3.0, depth),
                "duration_days": rng.randint(3, 7),
            },
            cost_inr=0.0,
            urgency="low",
            reasoning=f"Drive {category} volume with {depth:.1f}% discount -- trial this week.",
            week_submitted=week,
        ))

    # --- Loyalty program update (drift inflates perk cost) ---
    if rng.random() < 0.25 + drift * 0.1:
        idx += 1
        perk_cost = int(rng.randint(2, 8) * 1_00_000 * (1 + drift * 0.5))
        summaries = [
            "Add double-points weekend for loyalty members.",
            "Introduce tier-3 silver rewards for Rs 500+ baskets.",
            "Extend free-delivery perk to loyalty Gold members.",
            "Launch birthday-month bonus for repeat shoppers.",
        ]
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("growth", week, idx),
            dept="growth",
            action="loyalty.update",
            params={
                "perk_cost_inr": perk_cost,
                "change_summary": rng.choice(summaries),
            },
            cost_inr=-perk_cost,
            urgency="low",
            reasoning=(
                f"Loyalty perk update (Rs {perk_cost/1e5:.1f}L) to lift NPS "
                f"and repeat-purchase rate."
            ),
            week_submitted=week,
        ))

    # --- Competitor price match ---
    if rng.random() < 0.2 + drift * 0.15:
        idx += 1
        sku_id = rng.choice(list(ledger.sku_catalogue.keys()))
        sku = ledger.sku_catalogue[sku_id]
        competitor = rng.choice(["JioMart", "Blinkit", "Zepto", "DMart", "Reliance Fresh"])
        new_price = round(sku["price_inr"] * rng.uniform(0.88, 0.97), 2)
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("growth", week, idx),
            dept="growth",
            action="competitor.match",
            params={
                "sku_id": sku_id,
                "competitor": competitor,
                "new_price_inr": new_price,
            },
            cost_inr=0.0,
            urgency="med",
            reasoning=(
                f"{competitor} undercut {sku['name']} at Rs {new_price:.0f} "
                f"(ours Rs {sku['price_inr']:.0f}). Match to retain share."
            ),
            week_submitted=week,
        ))

    # --- Brand ambassador / influencer (drift inflates spend) ---
    if rng.random() < 0.1 + drift * 0.1:
        idx += 1
        names = [
            "Dhoni (regional cricket)",
            "Ranchi RJ Priya (radio)",
            "Local food-blogger Amit",
            "Jharkhand Kabaddi captain",
        ]
        ambassador_name = rng.choice(names)
        cost = int(rng.randint(3, 8) * 1_00_000 * (1 + drift))
        proposals.append(Proposal(
            proposal_id=_generate_proposal_id("growth", week, idx),
            dept="growth",
            action="brand.ambassador",
            params={
                "name": ambassador_name,
                "cost_inr": cost,
                "duration_weeks": rng.randint(2, 6),
            },
            cost_inr=-cost,
            urgency="low",
            reasoning=(
                f"Sign {ambassador_name} (Rs {cost/1e5:.1f}L) for regional "
                f"brand lift; projected NPS +1.5 over campaign period."
            ),
            week_submitted=week,
        ))

    return proposals


# ---------------------------------------------------------------------------
# Strategic opportunities (rare, high-ROI)
#   Action: strategic.opportunity
# ---------------------------------------------------------------------------

_STRATEGIC_OPPORTUNITIES = [
    {
        "name": "Exclusive regional supplier deal",
        "description": (
            "A regional FMCG supplier is exiting and offers exclusive distribution "
            "rights for their product line across our tier-2 network at a steep discount. "
            "3-month exclusivity window. Competitors have not been approached yet."
        ),
        "category": "fmcg",
        "cost_range": (15_00_000, 40_00_000),
    },
    {
        "name": "Dark store sublease in prime location",
        "description": (
            "A quick-commerce player is shutting down 3 dark stores in our core cities. "
            "We can sublease the cold-chain infrastructure at 40% below market rate. "
            "Would add 15-20% to our fresh category delivery capacity."
        ),
        "category": "fresh",
        "cost_range": (25_00_000, 60_00_000),
    },
    {
        "name": "Festival co-branding with major FMCG",
        "description": (
            "HUL/ITC is offering a co-branded festival promotion — they fund 60% of "
            "marketing, we provide shelf space and digital promotion. Projected footfall "
            "increase 25-35% during the campaign period."
        ),
        "category": "fmcg",
        "cost_range": (10_00_000, 25_00_000),
    },
    {
        "name": "Bulk procurement at distress pricing",
        "description": (
            "A competitor's warehouse liquidation offers staple inventory (wheat flour, rice, oil) "
            "at 25-30% below wholesale. Limited quantity — first-come-first-served. "
            "Would lock in 6-8 weeks of staple supply at exceptional margins."
        ),
        "category": "grocery_staple",
        "cost_range": (30_00_000, 80_00_000),
    },
    {
        "name": "Loyalty app partnership with Paytm/PhonePe",
        "description": (
            "Digital payments partner offers 6-month co-funded loyalty integration — "
            "cashback on every transaction routed through our stores. They cover 70% "
            "of cashback cost. Projected repeat-purchase lift of 8-12%."
        ),
        "category": "fmcg",
        "cost_range": (8_00_000, 20_00_000),
    },
    {
        "name": "Local celebrity brand endorsement at discount",
        "description": (
            "A well-known regional cricket/film personality's management has approached "
            "us with a below-market endorsement deal due to schedule availability. "
            "6-week campaign window. Projected NPS lift +3-5 points."
        ),
        "category": "fmcg",
        "cost_range": (12_00_000, 30_00_000),
    },
]


def strategic_opportunity_proposals(
    ledger: CompanyLedger,
    week: int,
    rng: random.Random,
) -> List[Proposal]:
    proposals: List[Proposal] = []
    if rng.random() >= E.STRATEGIC_OPP_PROB_PER_WEEK:
        return proposals

    opp = rng.choice(_STRATEGIC_OPPORTUNITIES)
    cost = rng.randint(opp["cost_range"][0], opp["cost_range"][1])
    rev_mult = round(rng.uniform(*E.STRATEGIC_OPP_REVENUE_MULT_RANGE), 2)
    duration = rng.randint(*E.STRATEGIC_OPP_DURATION_WEEKS_RANGE)

    proposals.append(Proposal(
        proposal_id=_generate_proposal_id("growth", week, 90),
        dept="growth",
        action="strategic.opportunity",
        params={
            "name": opp["name"],
            "cost_inr": cost,
            "category": opp["category"],
            "projected_revenue_mult": rev_mult,
            "duration_weeks": duration,
        },
        cost_inr=-cost,
        urgency="high",
        reasoning=(
            f"STRATEGIC OPPORTUNITY: {opp['description']} "
            f"Investment: Rs {cost/1e5:.0f}L. Projected revenue uplift: "
            f"+{(rev_mult-1)*100:.0f}% for {duration} weeks. "
            f"Time-sensitive — window closes this week."
        ),
        week_submitted=week,
    ))
    return proposals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _units_per_store_per_day(category: str) -> float:
    return float(E.CATEGORY_BASELINE_UNITS_PER_STORE_PER_DAY.get(category, 3.0))


def _days_of_stock_by_sku(ledger: CompanyLedger) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for sku_id, inv in ledger.inventory.items():
        sku = ledger.sku_catalogue[sku_id]
        daily = _units_per_store_per_day(sku["category"]) * E.TOTAL_STARTING_STORES
        out[sku_id] = inv["qty"] / max(1.0, daily)
    return out


def _festival_in_horizon(week: int, horizon_weeks: int) -> bool:
    start_day = (week - 1) * 7 + 1
    end_day = start_day + horizon_weeks * 7
    for d in range(start_day, min(end_day + 1, E.DEFAULT_DAYS_PER_QUARTER + 1)):
        fest = E.festival_for_day(d)
        if fest and fest["demand_mult"] > 1.4:
            return True
    return False


def _routine_filler(week: int, idx: int, rng: random.Random) -> Proposal:
    """Low-stakes filler when the dept pipeline is thin (keeps inbox >= MIN)."""
    return Proposal(
        proposal_id=_generate_proposal_id("store_ops", week, 90 + idx),
        dept="store_ops",
        action="planogram.update",
        params={"change_summary": "Shift end-caps to follow new loyalty promo cadence."},
        cost_inr=0.0,
        urgency="low",
        reasoning="Routine planogram refresh per monthly ops cadence.",
        week_submitted=week,
    )
