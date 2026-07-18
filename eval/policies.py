"""Baseline CEO policies — random, heuristic, oracle.

Used for establishing reward floor (random), ceiling (oracle), and a sensible
non-learned target (heuristic) that frontier models should beat.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from retailceo.models import (
    CEOAction,
    CEOObservation,
    CrisisEvent,
    Proposal,
    ProposalDecision,
)
from retailceo import economics as E


class CEOPolicy:
    """Interface: given an observation, return a CEOAction for this week."""

    name: str = "base"

    def act(
        self,
        obs: CEOObservation,
        env=None,
        week: int = 0,
    ) -> CEOAction:
        raise NotImplementedError

    def token_usage(self) -> Optional[Dict[str, int]]:
        """Cumulative token counters, or None if this policy has no LLM backend.

        Keys (when non-None): total_tokens, prompt_tokens, completion_tokens.
        """
        return None

    def estimate_cost_usd(
        self, prompt_tokens: Optional[int], completion_tokens: Optional[int]
    ) -> Optional[float]:
        """Rough USD cost for a token delta; None if pricing is unknown."""
        return None


# ---------------------------------------------------------------------------
# Random CEO
# ---------------------------------------------------------------------------

class RandomCEO(CEOPolicy):
    name = "random"

    def __init__(self, seed: int = 0):
        self._rng = random.Random(seed)

    def act(self, obs, env=None, week=0):
        verdicts = ["approve", "reject", "request_info"]
        weights = [0.65, 0.30, 0.05]
        decisions = [
            ProposalDecision(
                proposal_id=p.proposal_id,
                verdict=self._rng.choices(verdicts, weights=weights)[0],
            )
            for p in obs.inbox
        ]
        return CEOAction(
            decisions=decisions,
            budget_allocations={
                "supply_chain": 5e6,
                "store_ops": 5e5,
                "finance": 1e6,
                "growth": 1e6,
            },
            journal_entry=f"Random CEO, week {week}. No pattern.",
        )


# ---------------------------------------------------------------------------
# All-Approve CEO
# ---------------------------------------------------------------------------

class AllApproveCEO(CEOPolicy):
    name = "all_approve"

    def act(self, obs, env=None, week=0):
        decisions = [
            ProposalDecision(proposal_id=p.proposal_id, verdict="approve")
            for p in obs.inbox
        ]
        return CEOAction(
            decisions=decisions,
            budget_allocations={
                "supply_chain": 1e7,
                "store_ops": 2e6,
                "finance": 1e6,
                "growth": 2e6,
            },
            journal_entry=f"All-approve CEO, week {week}.",
        )


# ---------------------------------------------------------------------------
# Heuristic CEO — hand-coded but sensible; reads only the public observation
# ---------------------------------------------------------------------------

class HeuristicCEO(CEOPolicy):
    name = "heuristic"

    def __init__(self, cash_floor_inr: float = 3e7):
        self._cash_floor = cash_floor_inr

    @staticmethod
    def _crisis_flags(active: List[CrisisEvent]) -> Dict[str, bool]:
        return {c.crisis_id: True for c in active}

    @staticmethod
    def _cash_state(kpi, cash_floor_inr: float) -> str:
        runway = kpi.cash_runway_weeks
        if (
            kpi.cash_inr < cash_floor_inr
            or kpi.cash_pressure_score >= 0.8
            or kpi.cash_pressure_streak_weeks >= 3
            or (runway is not None and runway <= 3.0)
        ):
            return "crisis"
        warn_burn = E.STARTING_CASH_INR * E.CASH_BURN_WARN_PCT_OF_STARTING_CASH
        if (
            kpi.cash_pressure_score >= 0.4
            or kpi.cash_pressure_streak_weeks >= 2
            or kpi.cash_burn_rate_inr_per_week >= warn_burn
            or (runway is not None and runway <= E.CASH_RUNWAY_WARN_WEEKS)
        ):
            return "watch"
        return "stable"

    SPEND_CEILINGS_INR: Dict[str, float] = {
        "campaign.launch":   15_00_000,
        "capex.approve":     10_00_000,
        "return.approve":        50_000,
        "brand.ambassador":   5_00_000,
        "loyalty.update":     5_00_000,
        "hours.extend":          50_000,
    }

    def act(self, obs, env=None, week=0):
        decisions: List[ProposalDecision] = []
        cash_state = self._cash_state(obs.kpi_snapshot, self._cash_floor)
        crisis_active = self._crisis_flags(obs.active_crises)

        for p in obs.inbox:
            verdict, reason = self._decide(
                p, obs.kpi_snapshot, self._cash_floor, crisis_active
            )
            decisions.append(
                ProposalDecision(
                    proposal_id=p.proposal_id,
                    verdict=verdict,
                    reasoning=reason,
                )
            )

        if cash_state == "crisis":
            budget = {"supply_chain": 6e6, "store_ops": 5e5, "finance": 2e6, "growth": 2e5}
        elif cash_state == "watch":
            budget = {"supply_chain": 8e6, "store_ops": 1e6, "finance": 1.5e6, "growth": 5e5}
        else:
            budget = {"supply_chain": 1e7, "store_ops": 2e6, "finance": 1e6, "growth": 2e6}

        tight_cash = cash_state != "stable"
        journal = self._write_journal(obs, decisions, tight_cash, week)
        return CEOAction(
            decisions=decisions,
            budget_allocations=budget,
            journal_entry=journal,
        )

    @classmethod
    def _decide(cls, p, kpi, cash_floor_inr, crisis_active):
        params = p.params or {}
        cash_state = cls._cash_state(kpi, cash_floor_inr)
        cash_tight = cash_state != "stable"
        spend = cls._proposal_cash_spend(p)

        if p.action in {"po.place", "po.bulk_deal"}:
            sku_id = str(params.get("sku_id", "") or "")
            sku = E.SKU_CATALOGUE.get(sku_id)
            unit_cost = float(params.get("unit_cost", 0.0) or 0.0)
            qty = float(params.get("qty", 0.0) or 0.0)
            prep_for_crisis = bool(params.get("prep_for_crisis"))
            if sku and unit_cost > float(sku["cost_inr"]) * 1.15:
                return "reject", "Reject PO because unit cost is more than 15% above catalogue cost."
            expected_qty = cls._expected_restock_qty(sku_id)
            if expected_qty > 0 and not prep_for_crisis and qty > expected_qty * 1.9:
                return "reject", "Reject PO quantity far above expected restock need."

        if p.action == "line_of_credit.draw":
            if cash_tight or kpi.cash_inr < E.STARTING_CASH_INR * 0.70:
                return "approve", "Approve liquidity buffer because cash burn/runway is under pressure."
            return "reject", "Reject unnecessary debt while cash runway is stable."

        if p.action == "investor_report.flag":
            return "approve", "Approve transparency-only finance update."

        if p.action == "budget.reallocate":
            to_dept = str(params.get("to_dept", ""))
            if cash_tight and to_dept not in {"supply_chain", "finance"}:
                return "reject", "Reject budget move away from cash-preserving priorities."
            return "approve", "Approve budget move that does not directly burn cash."

        if p.action == "price.guardrail_change":
            delta = float(params.get("min_margin_delta_pts", 0.0))
            if cash_tight and delta < 0:
                return "reject", "Reject lower margin guardrail while cash is under pressure."
            return "approve", "Approve margin guardrail change compatible with cash state."

        if p.action in {"po.place", "po.bulk_deal"}:
            prep_for_crisis = bool(params.get("prep_for_crisis"))
            if cash_state == "crisis" and not prep_for_crisis and p.urgency == "low":
                return "reject", "Reject low-urgency inventory buy during cash crisis."
            if spend > max(kpi.cash_inr * 0.45, 3.0e7) and not prep_for_crisis and p.urgency != "high":
                return "reject", "Reject PO that would consume too much current cash."
            return "approve", "Approve inventory that protects revenue and stockout KPIs."

        if p.action == "vendor.switch":
            cost_delta = float(params.get("cost_delta_pct", 0.0))
            if cost_delta > (0.0 if cash_tight else 1.0):
                return "reject", "Reject vendor switch that worsens margin."
            return "approve", "Approve vendor switch with neutral or better unit economics."

        if p.action == "safety_stock.adjust":
            pct_delta = float(params.get("pct_delta", 0.0))
            if cash_state == "crisis" and pct_delta > 0:
                return "reject", "Reject safety-stock increase during cash crisis."
            return "approve", "Approve policy-only safety-stock adjustment."

        if p.action == "wastage.writeoff":
            if cash_state == "crisis" and kpi.stockout_rate_pct > E.STARTING_STOCKOUT_PCT:
                return "reject", "Reject writeoff while cash and stockouts are both stressed."
            return "approve", "Approve controlled wastage cleanup."

        if p.action == "staff.schedule":
            delta_hours = float(params.get("delta_hours", 0.0))
            if delta_hours <= 0:
                return "approve", "Approve staffing reduction/right-size move."
            if cash_state == "crisis" and p.urgency != "high":
                return "reject", "Reject extra staffing during cash crisis unless critical."
            if cash_state == "watch" and spend > 3.0e5 and kpi.delivery_sla_hit_rate_pct >= E.STARTING_SLA_HIT_RATE_PCT:
                return "reject", "Reject extra staffing because SLA is healthy and cash burn is elevated."
            return "approve", "Approve staffing that supports SLA and NPS."

        if p.action == "hours.extend":
            if cash_tight:
                return "reject", "Reject extended hours while cash burn is elevated."
            if spend > cls.SPEND_CEILINGS_INR["hours.extend"]:
                return "reject", "Reject extended hours above spend ceiling."
            return "approve", "Approve modest extended hours while cash is stable."

        if p.action == "return.approve":
            if cash_tight or spend > cls.SPEND_CEILINGS_INR["return.approve"]:
                return "reject", "Reject discretionary refund batch under cash/spend limits."
            return "approve", "Approve small refund batch while cash is stable."

        if p.action in {"local_promo.run", "discount.run"}:
            depth = float(params.get("discount_pct", params.get("depth_pct", 0.0)) or 0.0)
            if cash_tight and depth > 5.0:
                return "reject", "Reject deep discount because it worsens margin during cash pressure."
            if kpi.gross_margin_pct < E.STARTING_BLENDED_MARGIN_PCT and depth > 8.0:
                return "reject", "Reject discount while gross margin is already below baseline."
            return "approve", "Approve controlled promo/discount."

        if p.action == "campaign.launch":
            if cash_state == "crisis":
                return "reject", "Reject campaign spend during cash crisis."
            watch_ceiling = 6_00_000
            stable_ceiling = cls.SPEND_CEILINGS_INR["campaign.launch"]
            ceiling = watch_ceiling if cash_state == "watch" else stable_ceiling
            if spend > ceiling:
                return "reject", "Reject campaign spend above cash-state ROI ceiling."
            return "approve", "Approve campaign spend within cash-state ceiling."

        if p.action in {"loyalty.update", "brand.ambassador"}:
            ceiling = cls.SPEND_CEILINGS_INR.get(p.action, 0.0)
            if cash_tight or spend > ceiling:
                return "reject", "Reject discretionary brand/loyalty spend under cash pressure."
            return "approve", "Approve small brand/loyalty spend while cash is stable."

        if p.action in {"capex.approve", "city.enter", "franchise.onboard"}:
            payback_weeks = int(params.get("payback_weeks", 99) or 99)
            if cash_tight:
                return "reject", "Reject long-payback capital spend while cash burn is elevated."
            if spend > cls.SPEND_CEILINGS_INR.get("capex.approve", 10_00_000) or payback_weeks > 16:
                return "reject", "Reject capital spend above ceiling or with slow payback."
            return "approve", "Approve small fast-payback capital spend."

        if p.action == "competitor.match":
            if cash_tight and kpi.gross_margin_pct < E.STARTING_BLENDED_MARGIN_PCT:
                return "reject", "Reject price match because margin and cash are stressed."
            return "approve", "Approve tactical competitor match."

        ceiling = cls.SPEND_CEILINGS_INR.get(p.action)
        if ceiling is not None and spend > ceiling:
            return "reject", "Reject spend above heuristic ceiling."

        if p.urgency == "high":
            return "approve", "Approve high-urgency proposal."

        if p.urgency == "low" and cash_tight:
            return "reject", "Reject low-urgency proposal while cash is tight."

        return "approve", "Approve routine proposal."

    @staticmethod
    def _proposal_cash_spend(p: Proposal) -> float:
        if p.cost_inr < 0:
            return abs(float(p.cost_inr))
        params = p.params or {}
        candidates = [
            params.get("spend_inr"),
            params.get("amount_inr"),
            params.get("refund_inr"),
            params.get("perk_cost_inr"),
            params.get("cost_inr"),
            params.get("estimated_capex_inr"),
            params.get("onboarding_cost_inr"),
        ]
        if p.action == "hours.extend":
            candidates.append(
                float(params.get("hours", 0) or 0) * 60 * E.TOTAL_STARTING_STORES
            )
        if p.action in {"po.place", "po.bulk_deal"}:
            unit_cost = float(params.get("unit_cost", 0.0) or 0.0)
            if p.action == "po.bulk_deal":
                unit_cost *= 1.0 - float(params.get("discount_pct", 0.0) or 0.0) / 100.0
            candidates.append(float(params.get("qty", 0.0) or 0.0) * unit_cost)
        numeric = [float(v) for v in candidates if v not in (None, "")]
        return max([0.0] + numeric)

    @staticmethod
    def _expected_restock_qty(sku_id: str) -> float:
        sku = E.SKU_CATALOGUE.get(sku_id)
        if not sku:
            return 0.0
        category = sku["category"]
        target_days = (
            E.RESTOCK_TARGET_DAYS_PERISHABLE
            if E.CATEGORY_PERISHABLE.get(category, False)
            else E.RESTOCK_TARGET_DAYS_STAPLE
        )
        units_per_store_per_day = E.CATEGORY_BASELINE_UNITS_PER_STORE_PER_DAY.get(
            category, 0.0
        )
        return float(units_per_store_per_day) * E.TOTAL_STARTING_STORES * target_days

    @staticmethod
    def _write_journal(obs, decisions, tight_cash, week):
        n_reject = sum(1 for d in decisions if d.verdict == "reject")
        n_approve = sum(1 for d in decisions if d.verdict == "approve")
        n_info = sum(1 for d in decisions if d.verdict == "request_info")
        kpi = obs.kpi_snapshot
        active = [f"{c.crisis_id}:{c.name}" for c in obs.active_crises]
        runway = (
            f"{kpi.cash_runway_weeks:.1f}w"
            if kpi.cash_runway_weeks is not None
            else "stable"
        )
        return (
            f"Week {week}: {n_approve} approved, {n_reject} rejected, "
            f"{n_info} info requests. "
            f"Cash ₹{kpi.cash_inr/1e7:+.2f} Cr "
            f"(Δ₹{kpi.cash_delta_inr/1e7:+.2f}Cr, "
            f"burn ₹{kpi.cash_burn_rate_inr_per_week/1e7:.2f}Cr/wk, "
            f"runway={runway}, pressure={kpi.cash_pressure_score:.2f}, "
            f"cash-tight={tight_cash}), "
            f"NPS {kpi.nps:.0f}, stockout {kpi.stockout_rate_pct:.1f}%, "
            f"SLA {kpi.delivery_sla_hit_rate_pct:.0f}%. "
            f"Active crises: {', '.join(active) or 'none'}. "
            f"Next week: watch cash and supply-chain replenishment."
        )


# ---------------------------------------------------------------------------
# Oracle CEO — peeks at env.state for perfect crisis prep timing
# ---------------------------------------------------------------------------

class OracleCEO(HeuristicCEO):
    """Heuristic + cheats: peeks at env internal state for optimal decisions."""

    name = "oracle"

    FESTIVAL_DEMAND_MULTS = {
        "Diwali": 2.4, "Diwali pre-peak": 1.9, "Dhanteras": 1.6,
        "Dussehra": 1.25, "Dussehra peak": 1.35,
        "Chhath peak": 1.9, "Chhath pre-peak": 1.5,
        "Christmas day": 1.3, "Christmas week": 1.25,
        "New Year Eve": 1.4, "Holi": 1.6, "Eid": 1.7,
        "Pongal": 1.3, "Onam": 1.5, "Raksha Bandhan": 1.35,
    }

    def act(self, obs, env=None, week=0):
        if env is None:
            return super().act(obs, env, week)

        state = env._state
        crisis_queue = state.crisis_queue
        kpi = obs.kpi_snapshot
        cash = kpi.cash_inr
        cash_state = self._cash_state(kpi, self._cash_floor)
        current_day = state.day

        upcoming_crises = [
            c for c in crisis_queue
            if not c.active and c.started_day > current_day
            and c.started_day <= current_day + 21
        ]
        crisis_imminent = len(upcoming_crises) > 0

        base_action = super().act(obs, env, week)

        overrides: dict[str, tuple[str, str]] = {}
        for p in obs.inbox:
            override = self._oracle_override(
                p, kpi, cash, cash_state, crisis_imminent, upcoming_crises, env,
            )
            if override:
                overrides[p.proposal_id] = override

        if not overrides:
            return base_action

        new_decisions = []
        for d in base_action.decisions:
            if d.proposal_id in overrides:
                verdict, reason = overrides[d.proposal_id]
                new_decisions.append(ProposalDecision(
                    proposal_id=d.proposal_id, verdict=verdict, reasoning=reason,
                ))
            else:
                new_decisions.append(d)

        base_action.decisions = new_decisions
        return base_action

    @classmethod
    def _oracle_override(cls, p, kpi, cash, cash_state, crisis_imminent,
                         upcoming_crises, env):
        """Return (verdict, reason) to override Heuristic, or None to keep it."""
        params = p.params or {}

        if p.action in {"po.place", "po.bulk_deal"}:
            prep_for_crisis = bool(params.get("prep_for_crisis"))
            if prep_for_crisis and cash_state != "crisis":
                return "approve", "Oracle: approve crisis-prep PO with foresight."
            return None

        return None
