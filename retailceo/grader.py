"""RetailCEO-Bench reward grader — dense operating reward plus terminal P&L/liquidity.

Ported from SimMart grader.py.  Changes:
    • Imports from retailceo.models / retailceo.economics
    • rogue_catch_score() removed (no governance curriculum)
    • journal_coherence_score() removed (unused in reward)
    • rogue_metrics parameter removed from weekly_reward()

Formula:
    R_weekly =
        0.25 × kpi_delta_score           (weekly, returned each step)
      - 0.05 × stockout_penalty           (weekly)
      - 0.05 × cash_pressure_penalty      (weekly)

    R_terminal =
        0.70 × quarterly_pnl_bonus        (terminal only)
      - 0.60 × cash_floor_penalty          (terminal only)

Components stay in [-1, +1] before weighting so the weighted sum also
falls in a well-bounded range.

Public API:
    weekly_reward(...)      → (float, Dict[str, float])   per-week total + components
    terminal_reward(...)    → (float, Dict[str, float])   episode-end terminal bonus + components
    kpi_delta_score(kpi)
    false_reject_penalty(decisions, inbox)
    stockout_penalty(kpi)
    cash_pressure_penalty(kpi)
    quarterly_pnl_bonus(ledger)
    cash_floor_penalty(min_cash_inr)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from retailceo.models import (
    CompanyLedger,
    KPISnapshot,
    Proposal,
    ProposalDecision,
)
from retailceo import economics as E


# ---------------------------------------------------------------------------
# Individual components (each returns a normalised signal in [-1, +1] or [0, 1])
# ---------------------------------------------------------------------------

def kpi_delta_score(kpi: KPISnapshot) -> float:
    """Average of 5 KPI levels measured against the starting baseline target.

    Per-component score = clip((level - target) / normaliser, -1, +1).
    Stockout is INVERTED so that *lower* stockouts score positive.

    Why level (not week-over-week delta)?  A delta-based score punishes
    turbulence: a steady decline scores negative every week even at a
    constant rate of slip, so the cumulative reward is the integral of
    decline.  With level scoring, a do-nothing-perfectly policy that
    holds at baseline scores 0/wk; any improvement above baseline scores
    positive; any deficit scores proportional to its current size, not
    its derivative.  This gives GRPO a well-shaped landscape with a
    clean zero-point.
    """
    t = E.KPI_TARGETS
    n = E.KPI_LEVEL_NORMALISERS
    scores = [
        _clip_to_unit((kpi.revenue_inr - t["revenue_inr"]) / n["revenue_inr"]),
        _clip_to_unit((kpi.gross_margin_pct - t["gross_margin_pct"]) / n["gross_margin_pct"]),
        -_clip_to_unit((kpi.stockout_rate_pct - t["stockout_rate_pct"]) / n["stockout_rate_pct"]),
        _clip_to_unit((kpi.nps - t["nps"]) / n["nps"]),
        _clip_to_unit((kpi.delivery_sla_hit_rate_pct - t["delivery_sla_hit_rate_pct"]) / n["delivery_sla_hit_rate_pct"]),
    ]
    return sum(scores) / len(scores)


def false_reject_penalty(
    decisions: List[ProposalDecision],
    inbox: List[Proposal],
) -> float:
    """Weighted count of rejections, normalised by inbox size.

    Weights:
        high urgency → 1.0  (most costly to reject incorrectly)
        med  urgency → 0.5
        low  urgency → 0.1

    A pure `reject-all` baseline on an 11-proposal inbox averaging med-urgency
    scores roughly 0.5 (then −0.3 weight → -0.15 component, potentially
    worse with the stockout penalty that follows).  Oracle CEO: 0.0.
    """
    if not inbox:
        return 0.0
    inbox_by_id = {p.proposal_id: p for p in inbox}
    weights = {"high": 1.0, "med": 0.5, "low": 0.1}
    total = 0.0
    for d in decisions:
        if d.verdict != "reject":
            continue
        prop = inbox_by_id.get(d.proposal_id)
        if prop is None:
            continue
        total += weights.get(prop.urgency, 0.5)
    return min(1.0, total / max(1, len(inbox)))


def stockout_penalty(kpi: KPISnapshot) -> float:
    """Return a [0, 1] penalty proportional to stockout rate over 5 %.

    Per economics.py STOCKOUT_PER_PT_PENALTY = 0.05/pt, so 25 pp over the
    threshold maxes the penalty at 1.0.
    """
    excess_pts = max(0.0, kpi.stockout_rate_pct - 5.0)
    return min(1.0, excess_pts * E.STOCKOUT_PER_PT_PENALTY)


def cash_pressure_penalty(kpi: KPISnapshot) -> float:
    """Return a [0, 1] liquidity warning before cash goes negative.

    The baseline term scales with absolute cash loss from the starting cash
    balance, so a company at ₹12Cr from a ₹15Cr start carries 0.20 pressure
    even if this week's burn has paused.  Burn/runway can raise that further.
    """
    if kpi.cash_pressure_score > 0:
        return max(0.0, min(1.0, kpi.cash_pressure_score))

    cash_inr = getattr(kpi, "cash_inr", E.STARTING_CASH_INR)
    cash_shortfall_score = _clip01((E.STARTING_CASH_INR - cash_inr) / E.STARTING_CASH_INR)
    burn_rate = max(0.0, getattr(kpi, "cash_burn_rate_inr_per_week", 0.0))
    warn_burn = E.STARTING_CASH_INR * E.CASH_BURN_WARN_PCT_OF_STARTING_CASH
    critical_burn = E.STARTING_CASH_INR * E.CASH_BURN_CRITICAL_PCT_OF_STARTING_CASH
    burn_score = _clip01((burn_rate - warn_burn) / max(1.0, critical_burn - warn_burn))

    runway_score = 0.0
    runway = getattr(kpi, "cash_runway_weeks", None)
    if runway is not None:
        runway_score = _clip01((E.CASH_RUNWAY_WARN_WEEKS - runway) / E.CASH_RUNWAY_WARN_WEEKS)

    score = max(cash_shortfall_score, burn_score, runway_score)
    if (
        getattr(kpi, "cash_pressure_streak_weeks", 0)
        >= E.CASH_PRESSURE_PERSISTENCE_WEEKS
        and burn_rate >= warn_burn
    ):
        score = max(score, 0.5)
    return score


def quarterly_pnl_bonus(ledger: CompanyLedger) -> float:
    """Map QTD EBITDA margin to [-1, +1] (linear, clipped at -13%/+7%).

    Breakeven shifted to -3% (was 0%) — running the business at flat EBITDA
    is itself a small win in this environment (positive cash retention,
    profitable inventory turns), so it should reward, not zero out.

    Anchors:
        -13% → -1.0  (deep cash-burn, floor)
        -3 % →  0.0  (true break-even of the env: opex covered, no cushion)
        +2 % → +0.5  (oracle-tier operating result)
        +7 % → +1.0  (ceiling, stretch target)
    """
    margin_pct = ledger.pnl_qtd.ebitda_margin_pct
    mapped = (margin_pct + 3.0) / 10.0
    return max(-1.0, min(1.0, mapped))


def cash_floor_penalty(min_cash_inr: float, starting_cash_inr: float | None = None) -> float:
    """Continuous penalty in [0, 1] when min cash dropped below 50% of starting.

    Linear ramp:
        cash >= 50% of starting → 0.0  (well managed)
        cash =   0%             → 1.0  (broke)
        cash <   0%             → clipped at 1.0
    """
    if starting_cash_inr is None:
        starting_cash_inr = E.STARTING_CASH_INR
    threshold = starting_cash_inr * 0.50
    if min_cash_inr >= threshold:
        return 0.0
    if min_cash_inr <= 0:
        return 1.0
    return min(1.0, (threshold - min_cash_inr) / max(1.0, threshold))


def free_cash_flow_score(cash_this_week: float, cash_last_week: float) -> float:
    """Reward positive cash generation, penalize cash burn. Returns [-1, +1]."""
    delta = cash_this_week - cash_last_week
    normalizer = 5e7
    return max(-1.0, min(1.0, delta / normalizer))


# ---------------------------------------------------------------------------
# Weekly + Terminal roll-up
# ---------------------------------------------------------------------------

def weekly_reward(
    kpi_snapshot: KPISnapshot,
    decisions: List[ProposalDecision],
    inbox: List[Proposal],
    journal_entry: str,
    prev_journal_entry: str = "",
    cash_this_week: float | None = None,
    cash_last_week: float | None = None,
) -> Tuple[float, Dict[str, float]]:
    """Compute this week's reward and per-component breakdown."""
    raw: Dict[str, float] = {
        "kpi_delta":         kpi_delta_score(kpi_snapshot),
        "stockout":          stockout_penalty(kpi_snapshot),
        "cash_pressure":     cash_pressure_penalty(kpi_snapshot),
        "false_reject":      false_reject_penalty(decisions, inbox),
    }
    if cash_this_week is not None and cash_last_week is not None:
        raw["fcf"] = free_cash_flow_score(cash_this_week, cash_last_week)
    else:
        raw["fcf"] = 0.0

    w = E.REWARD_WEIGHTS
    weighted: Dict[str, float] = {
        "kpi_delta":         w["weekly_kpi_delta"] * raw["kpi_delta"],
        "fcf":               w["weekly_fcf"]       * raw["fcf"],
        "stockout":          w["stockout"]          * raw["stockout"],
        "cash_pressure":     w["cash_pressure"]     * raw["cash_pressure"],
        "false_reject":      w["false_reject"]      * raw["false_reject"],
    }

    total = sum(weighted.values())
    out = {f"raw.{k}": v for k, v in raw.items()}
    out.update({f"weighted.{k}": v for k, v in weighted.items()})
    out["total"] = total
    return total, out


def quarterly_scorecard(
    ledger: CompanyLedger,
    min_cash_quarter: float,
) -> Tuple[float, Dict[str, float]]:
    """Mini terminal reward at each quarter boundary for multi-year episodes."""
    raw = {
        "quarterly_pnl": quarterly_pnl_bonus(ledger),
        "cash_floor": cash_floor_penalty(min_cash_quarter),
    }
    weighted = {
        "quarterly_pnl": 0.15 * raw["quarterly_pnl"],
        "cash_floor": -0.10 * raw["cash_floor"],
    }
    total = sum(weighted.values())
    out = {f"raw.{k}": v for k, v in raw.items()}
    out.update({f"weighted.{k}": v for k, v in weighted.items()})
    out["total"] = total
    return total, out


def terminal_reward(
    ledger: CompanyLedger,
    min_cash_inr: float,
) -> Tuple[float, Dict[str, float]]:
    """Terminal reward applied at the final step of the episode."""
    raw = {
        "quarterly_pnl": quarterly_pnl_bonus(ledger),
        "cash_floor": cash_floor_penalty(min_cash_inr),
    }
    w = E.REWARD_WEIGHTS
    weighted = {
        "quarterly_pnl": w["quarterly_pnl"] * raw["quarterly_pnl"],
        "cash_floor": w["cash_floor"] * raw["cash_floor"],
    }
    total = sum(weighted.values())
    out = {f"raw.{k}": v for k, v in raw.items()}
    out.update({f"weighted.{k}": v for k, v in weighted.items()})
    out["total"] = total
    return total, out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clip_to_unit(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))
