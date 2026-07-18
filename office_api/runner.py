"""Async event stream for live Retail CEO episodes (bench-backed).

Drives a real ``RetailCEOEnv`` episode with a scripted policy and yields the
same UI event shape the Office frontend consumes:

    run_started -> (week_started -> agent_thinking -> agent_called
                    -> week_completed) * N -> run_completed / run_failed
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Dict, List

from retailceo.environment import RetailCEOEnv
from retailceo.models import BenchmarkConfig

from .policies import build_policy
from .schemas import RunConfig
from .trace import serialize_inbox, serialize_week, summarize_run


def _event(event_type: str, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": event_type,
        "run_id": run_id,
        "ts": time.time(),
        "payload": payload,
    }


def _crisis_ids(active_crises: List[Any]) -> List[str]:
    return [crisis.crisis_id for crisis in active_crises]


async def stream_run(run_id: str, config: RunConfig) -> AsyncIterator[Dict[str, Any]]:
    """Run one episode and yield UI-friendly events as each week completes."""

    started_at = time.time()
    bench_config = BenchmarkConfig(
        weeks_per_quarter=config.weeks,
        difficulty=config.difficulty,
        seed=config.seed,
    )
    env = RetailCEOEnv(bench_config)
    policy = build_policy(config)
    obs = env.reset(seed=config.seed)

    weekly_rewards: List[float] = []
    stockouts: List[float] = []
    nps_values: List[float] = []
    weeks: List[Dict[str, Any]] = []
    min_cash = env.state.company.cash_inr

    yield _event(
        "run_started",
        run_id,
        {
            "config": config.model_dump(),
            "policy_name": policy.name,
            "max_weeks": env.MAX_WEEKS,
            "difficulty": config.difficulty,
            "initial_kpi": obs.kpi_snapshot.model_dump() if obs.kpi_snapshot else {},
            "initial_pnl": obs.pnl_snapshot.model_dump()
            if getattr(obs, "pnl_snapshot", None)
            else {},
        },
    )

    for week in range(1, env.MAX_WEEKS + 1):
        inbox_snapshot = serialize_inbox(obs.inbox)
        active_crises = _crisis_ids(obs.active_crises)

        yield _event(
            "week_started",
            run_id,
            {
                "week": week,
                "inbox": inbox_snapshot,
                "active_crises": active_crises,
                "kpi": obs.kpi_snapshot.model_dump() if obs.kpi_snapshot else {},
                "pnl_qtd": obs.pnl_snapshot.model_dump()
                if getattr(obs, "pnl_snapshot", None)
                else {},
            },
        )
        yield _event(
            "agent_thinking",
            run_id,
            {
                "week": week,
                "policy_name": policy.name,
                "message": "CEO is reviewing department proposals.",
            },
        )

        action_started_at = time.time()
        action = await asyncio.to_thread(policy.act, obs, env, week)
        yield _event(
            "agent_called",
            run_id,
            {
                "week": week,
                "policy_name": policy.name,
                "wall_s": time.time() - action_started_at,
            },
        )

        step_obs = env.step(action)
        reward = step_obs.reward or 0.0
        weekly_rewards.append(reward)
        if step_obs.kpi_snapshot:
            stockouts.append(step_obs.kpi_snapshot.stockout_rate_pct)
            nps_values.append(step_obs.kpi_snapshot.nps)
        min_cash = min(min_cash, env.state.company.cash_inr)

        week_payload = serialize_week(
            week=week,
            obs=obs,
            step_obs=step_obs,
            action=action,
            inbox_snapshot=inbox_snapshot,
            active_crises=active_crises,
        )
        weeks.append(week_payload)
        yield _event("week_completed", run_id, week_payload)

        obs = step_obs
        if obs.done:
            break

    summary = summarize_run(
        env=env,
        policy_name=policy.name,
        seed=config.seed,
        difficulty=config.difficulty,
        started_at=started_at,
        weekly_rewards=weekly_rewards,
        stockouts=stockouts,
        nps_values=nps_values,
        min_cash_inr=min_cash,
    )
    summary["weeks"] = weeks
    yield _event("run_completed", run_id, summary)
