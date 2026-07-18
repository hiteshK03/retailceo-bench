"""Interactive (human-driven) Retail CEO episode runner.

Turn-taking over a bidirectional channel: emit ``week_started``, await the
human's decisions, step the env, emit ``week_completed``; repeat; then write a
recording and emit ``run_completed``. Decoupled from the transport via the
``recv_decisions`` / ``emit`` callables so it is unit-testable in-process.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List

from retailceo.environment import RetailCEOEnv
from retailceo.models import BenchmarkConfig, CEOAction, ProposalDecision

from .schemas import RunConfig
from .trace import serialize_inbox, serialize_week, summarize_run

_VALID_VERDICTS = {"approve", "reject", "modify", "request_info"}


def _event(event_type: str, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": event_type, "run_id": run_id, "ts": time.time(), "payload": payload}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_human_action(inbox, raw_decisions, journal: str = "") -> CEOAction:
    """Assemble a CEOAction from a human's raw decision dicts.

    Missing proposals default to request_info (a ledger no-op, matching
    prompts.parse_response); unknown ids are dropped; invalid verdicts ->
    request_info.
    """
    by_id = {p.proposal_id for p in inbox}
    seen: set = set()
    decisions: List[ProposalDecision] = []
    for d in raw_decisions or []:
        pid = d.get("proposal_id")
        if pid is None or pid not in by_id or pid in seen:
            continue
        verdict = d.get("verdict", "request_info")
        if verdict not in _VALID_VERDICTS:
            verdict = "request_info"
        kwargs: Dict[str, Any] = {"proposal_id": pid, "verdict": verdict}
        mp = d.get("modified_params")
        if isinstance(mp, dict):
            kwargs["modified_params"] = mp
        if isinstance(d.get("reasoning"), str):
            kwargs["reasoning"] = d["reasoning"]
        decisions.append(ProposalDecision(**kwargs))
        seen.add(pid)
    for p in inbox:
        if p.proposal_id not in seen:
            decisions.append(
                ProposalDecision(proposal_id=p.proposal_id, verdict="request_info")
            )
    return CEOAction(action_type="decide", decisions=decisions, journal_entry=journal or "")


def write_recording(
    config: RunConfig,
    summary: Dict[str, Any],
    results_dir: str = "results/human",
) -> str:
    """Write a completed human playthrough as an eval-format trace JSON."""
    os.makedirs(results_dir, exist_ok=True)
    handle = (config.player_handle or "anonymous").strip() or "anonymous"
    safe = "".join(c for c in handle if c.isalnum() or c in "-_")[:32] or "anon"
    short = uuid.uuid4().hex[:8]
    fname = f"{config.difficulty}_seed{config.seed}_{safe}_{short}.json"
    path = os.path.join(results_dir, fname)
    s = summary.get("summary", {})
    payload = {
        "meta": {
            "policy": "human",
            "mode": "human",
            "player_handle": handle,
            "seed": config.seed,
            "difficulty": config.difficulty,
            "played_at": summary.get("played_at") or _iso_now(),
            "total_reward": s.get("total_reward"),
            "final_cash_inr": s.get("final_cash_inr"),
            "ebitda_margin_pct": s.get("ebitda_margin_pct"),
            "avg_stockout_pct": s.get("avg_stockout_pct"),
            "avg_nps": s.get("avg_nps"),
        },
        "trace": summary.get("weeks", []),
        "summary": s,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


async def play_interactive(
    run_id: str,
    config: RunConfig,
    recv_decisions: Callable[[], Awaitable[Dict[str, Any]]],
    emit: Callable[[Dict[str, Any]], Awaitable[None]],
) -> Dict[str, Any]:
    started_at = time.time()
    bench = BenchmarkConfig(
        weeks_per_quarter=config.weeks,
        difficulty=config.difficulty,
        seed=config.seed,
    )
    env = RetailCEOEnv(bench)
    obs = env.reset(seed=config.seed)

    weekly_rewards: List[float] = []
    stockouts: List[float] = []
    nps_values: List[float] = []
    weeks: List[Dict[str, Any]] = []
    min_cash = env.state.company.cash_inr

    await emit(_event("run_started", run_id, {
        "config": config.model_dump(),
        "policy_name": "human",
        "max_weeks": env.MAX_WEEKS,
        "difficulty": config.difficulty,
        "initial_kpi": obs.kpi_snapshot.model_dump() if obs.kpi_snapshot else {},
        "initial_pnl": obs.pnl_snapshot.model_dump()
        if getattr(obs, "pnl_snapshot", None) else {},
    }))

    for week in range(1, env.MAX_WEEKS + 1):
        inbox_snapshot = serialize_inbox(obs.inbox)
        active = [c.crisis_id for c in obs.active_crises]
        await emit(_event("week_started", run_id, {
            "week": week,
            "inbox": inbox_snapshot,
            "active_crises": active,
            "kpi": obs.kpi_snapshot.model_dump() if obs.kpi_snapshot else {},
            "pnl_qtd": obs.pnl_snapshot.model_dump()
            if getattr(obs, "pnl_snapshot", None) else {},
        }))

        wait_start = time.time()
        msg = await recv_decisions()
        if int(msg.get("week", -1)) != week:
            raise ValueError(
                f"decision week {msg.get('week')} != expected {week}"
            )
        decision_wall_s = time.time() - wait_start

        action = build_human_action(
            obs.inbox, msg.get("decisions", []), msg.get("journal", "")
        )
        step_obs = env.step(action)
        reward = step_obs.reward or 0.0
        weekly_rewards.append(reward)
        if step_obs.kpi_snapshot:
            stockouts.append(step_obs.kpi_snapshot.stockout_rate_pct)
            nps_values.append(step_obs.kpi_snapshot.nps)
        min_cash = min(min_cash, env.state.company.cash_inr)

        payload = serialize_week(
            week=week, obs=obs, step_obs=step_obs, action=action,
            inbox_snapshot=inbox_snapshot, active_crises=active,
        )
        payload["decision_wall_s"] = decision_wall_s
        weeks.append(payload)
        await emit(_event("week_completed", run_id, payload))

        obs = step_obs
        if obs.done:
            break

    summary = summarize_run(
        env=env, policy_name="human", seed=config.seed,
        difficulty=config.difficulty, started_at=started_at,
        weekly_rewards=weekly_rewards, stockouts=stockouts,
        nps_values=nps_values, min_cash_inr=min_cash,
    )
    summary["weeks"] = weeks
    summary["played_at"] = _iso_now()
    summary["recording_path"] = write_recording(config, summary)
    await emit(_event("run_completed", run_id, summary))
    return summary
