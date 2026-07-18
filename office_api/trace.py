"""Trace serialization for live Retail CEO Office runs.

Adapted from the SimMart Office trace serializer. The bench grader explicitly
removed the rogue/governance mechanic, so there is NO rogue ground truth to
emit here — all rogue-only serialization has been dropped. The Office frontend
gracefully hides rogue UI when the data is absent.
"""

from __future__ import annotations

import statistics
import time
from typing import Any, Dict, Iterable, List


def serialize_inbox(inbox: Iterable[Any]) -> List[Dict[str, Any]]:
    """Serialize the current weekly proposals for the office UI."""

    return [proposal.model_dump() for proposal in inbox]


def serialize_week(
    *,
    week: int,
    obs: Any,
    step_obs: Any,
    action: Any,
    inbox_snapshot: List[Dict[str, Any]],
    active_crises: List[str],
) -> Dict[str, Any]:
    reward = step_obs.reward or 0.0
    return {
        "week": week,
        "day_of_quarter": getattr(step_obs, "day_of_quarter", None),
        "active_crises": active_crises,
        "inbox": inbox_snapshot,
        "decisions": [decision.model_dump() for decision in action.decisions],
        "budget_allocations": getattr(action, "budget_allocations", {}) or {},
        "journal": action.journal_entry,
        "reward": reward,
        # The CEO's action + journal are produced from `obs` (pre-step). The
        # primary `kpi`/`pnl_qtd` fields below are post-close (from step_obs).
        "decision_kpi": obs.kpi_snapshot.model_dump() if obs.kpi_snapshot else {},
        "decision_pnl_qtd": obs.pnl_snapshot.model_dump()
        if getattr(obs, "pnl_snapshot", None)
        else {},
        "kpi": step_obs.kpi_snapshot.model_dump() if step_obs.kpi_snapshot else {},
        "pnl_qtd": step_obs.pnl_snapshot.model_dump()
        if getattr(step_obs, "pnl_snapshot", None)
        else {},
        "cash_inr": step_obs.kpi_snapshot.cash_inr
        if step_obs.kpi_snapshot
        else getattr(obs.kpi_snapshot, "cash_inr", 0.0),
    }


def summarize_run(
    *,
    env: Any,
    policy_name: str,
    seed: int,
    difficulty: str,
    started_at: float,
    weekly_rewards: List[float],
    stockouts: List[float],
    nps_values: List[float],
    min_cash_inr: float,
) -> Dict[str, Any]:
    company = env.state.company
    return {
        "policy": policy_name,
        "seed": seed,
        "difficulty": difficulty,
        "summary": {
            "total_reward": sum(weekly_rewards),
            "weekly_rewards": weekly_rewards,
            "ebitda_margin_pct": company.pnl_qtd.ebitda_margin_pct,
            "ebitda_qtd_inr": company.pnl_qtd.ebitda_qtd_inr,
            "revenue_qtd_inr": company.pnl_qtd.revenue_qtd_inr,
            "final_cash_inr": company.cash_inr,
            "min_cash_inr": min_cash_inr,
            "avg_stockout_pct": statistics.mean(stockouts) if stockouts else 0.0,
            "avg_nps": statistics.mean(nps_values) if nps_values else 0.0,
            "wall_s": time.time() - started_at,
        },
    }
