"""Evaluation runner — single-episode rollouts and multi-seed sweeps."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from retailceo.models import BenchmarkConfig
from retailceo.environment import RetailCEOEnv
from .policies import CEOPolicy


@dataclass
class EpisodeResult:
    policy: str
    seed: int
    total_reward: float
    weekly_rewards: List[float]
    starting_cash_inr: float
    final_cash_inr: float
    revenue_qtd_inr: float
    ebitda_qtd_inr: float
    ebitda_margin_pct: float
    min_cash_inr: float
    avg_stockout_pct: float
    avg_nps: float
    difficulty: str = "medium"
    trace: Optional[List[Dict]] = field(default=None)

    @property
    def free_cash_flow_inr(self) -> float:
        return self.final_cash_inr - self.starting_cash_inr

    @property
    def cash_retained_pct(self) -> float:
        if self.starting_cash_inr == 0:
            return 0.0
        return (self.final_cash_inr / self.starting_cash_inr) * 100.0


def run_one_episode(
    policy: CEOPolicy,
    seed: int,
    config: Optional[BenchmarkConfig] = None,
    collect_trace: bool = False,
    verbose: bool = False,
) -> EpisodeResult:
    env = RetailCEOEnv(config)
    obs = env.reset(seed=seed)
    weekly_rewards: List[float] = []
    stockouts: List[float] = []
    npss: List[float] = []
    trace: Optional[List[Dict]] = [] if collect_trace else None

    starting_cash = env.state.company.cash_inr
    min_cash = starting_cash

    for w in range(1, env.MAX_WEEKS + 1):
        action = policy.act(obs, env=env, week=w)
        step_obs = env.step(action)

        r = step_obs.reward or 0.0
        weekly_rewards.append(r)
        stockouts.append(step_obs.kpi_snapshot.stockout_rate_pct)
        npss.append(step_obs.kpi_snapshot.nps)
        min_cash = min(min_cash, env.state.company.cash_inr)

        if collect_trace and trace is not None:
            trace.append({
                "week": w,
                "day": step_obs.day_of_quarter,
                "inbox_size": len(obs.inbox),
                "decisions": [d.model_dump() for d in action.decisions],
                "budget_allocations": action.budget_allocations,
                "journal": action.journal_entry,
                "reward": r,
                "kpi": step_obs.kpi_snapshot.model_dump(),
                "active_crises": [c.crisis_id for c in step_obs.active_crises],
                "pnl_qtd": step_obs.pnl_snapshot.model_dump(),
            })

        if verbose:
            print(
                f"  W{w:2d}  r={r:+.3f}  "
                f"rev=₹{step_obs.kpi_snapshot.revenue_inr/1e7:.2f}Cr  "
                f"margin={step_obs.kpi_snapshot.gross_margin_pct:5.2f}%  "
                f"NPS={step_obs.kpi_snapshot.nps:4.1f}  "
                f"stockout={step_obs.kpi_snapshot.stockout_rate_pct:5.1f}%  "
                f"cash=₹{env.state.company.cash_inr/1e7:+.2f}Cr"
            )

        obs = step_obs
        if obs.done:
            break

    env.close()

    return EpisodeResult(
        policy=policy.name,
        seed=seed,
        total_reward=sum(weekly_rewards),
        weekly_rewards=weekly_rewards,
        starting_cash_inr=starting_cash,
        final_cash_inr=env.state.company.cash_inr,
        revenue_qtd_inr=env.state.company.pnl_qtd.revenue_qtd_inr,
        ebitda_qtd_inr=env.state.company.pnl_qtd.ebitda_qtd_inr,
        ebitda_margin_pct=env.state.company.pnl_qtd.ebitda_margin_pct,
        min_cash_inr=min_cash,
        avg_stockout_pct=statistics.mean(stockouts) if stockouts else 0.0,
        avg_nps=statistics.mean(npss) if npss else 0.0,
        difficulty=config.difficulty if config else "medium",
        trace=trace,
    )


def run_policy(
    policy: CEOPolicy,
    seeds: List[int],
    config: Optional[BenchmarkConfig] = None,
    verbose: bool = False,
    quiet: bool = False,
) -> List[EpisodeResult]:
    results: List[EpisodeResult] = []
    for seed in seeds:
        if not quiet:
            print(f"\n[{policy.name}] seed={seed} rollout …")
        res = run_one_episode(
            policy, seed, config=config, collect_trace=False, verbose=verbose,
        )
        results.append(res)
        if not quiet:
            print(
                f"  → reward {res.total_reward:+.3f},  "
                f"EBITDA {res.ebitda_margin_pct:+.1f}%,  "
                f"stockout {res.avg_stockout_pct:.1f}%,  "
                f"cash ₹{res.starting_cash_inr/1e7:.0f}Cr→₹{res.final_cash_inr/1e7:+.1f}Cr "
                f"(FCF ₹{res.free_cash_flow_inr/1e7:+.1f}Cr, "
                f"retained {res.cash_retained_pct:.0f}%)"
            )
    return results


def summarise(results_by_policy: Dict[str, List[EpisodeResult]]) -> None:
    header = (
        f"{'policy':<20} {'n':>3}  "
        f"{'tot_r (mean±sd)':>18}  {'EBITDA%':>7}  "
        f"{'stockout%':>9}  {'NPS':>5}  "
        f"{'start_cash':>11}  {'final_cash':>11}  "
        f"{'FCF':>11}  {'cash_ret%':>9}"
    )
    print("\n" + header)
    print("-" * len(header))
    for name, res in results_by_policy.items():
        if not res:
            continue
        rewards = [r.total_reward for r in res]
        mean_r = statistics.mean(rewards)
        sd_r = statistics.stdev(rewards) if len(rewards) > 1 else 0.0
        ebitda_pct = statistics.mean([r.ebitda_margin_pct for r in res])
        stockout = statistics.mean([r.avg_stockout_pct for r in res])
        nps = statistics.mean([r.avg_nps for r in res])
        start_cash = statistics.mean([r.starting_cash_inr for r in res])
        final_cash = statistics.mean([r.final_cash_inr for r in res])
        fcf = statistics.mean([r.free_cash_flow_inr for r in res])
        cash_ret = statistics.mean([r.cash_retained_pct for r in res])
        print(
            f"{name:<20} {len(res):>3}  "
            f"{mean_r:+7.3f} ± {sd_r:5.3f}    "
            f"{ebitda_pct:+6.2f}  "
            f"{stockout:8.1f}  "
            f"{nps:5.1f}  "
            f"{start_cash/1e7:+10.1f}  "
            f"{final_cash/1e7:+10.1f}  "
            f"{fcf/1e7:+10.1f}  "
            f"{cash_ret:8.1f}"
        )
