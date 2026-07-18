"""OpenEnv adapter over ``retailceo.environment.RetailCEOEnv``.

This is a thin adapter: it does not reimplement any simulation logic.  It maps
the benchmark's ``reset()/step()`` onto the OpenEnv ``Environment`` interface,
routing agent text through the benchmark's own ``prompts.parse_response`` and
rendering observations with the benchmark's own ``prompts.render_observation``.

Train/eval separation (IMPORTANT — read this)
---------------------------------------------
In this benchmark a *seed* fully determines an episode (crisis schedule,
proposal stream, dept drift, festival timing).  The public leaderboard is
scored on a fixed, small set of seeds (``RESERVED_EVAL_SEEDS`` below).  If RL
training were allowed to reset on those same seeds, a policy could memorise the
exact eval episodes — train-on-test leakage, even though no dataset is shared.

To prevent that, this env:
  * refuses reserved eval seeds by default (raises unless ``allow_eval_seeds``);
  * draws training episodes from a disjoint pool (seed >= ``TRAIN_SEED_FLOOR``)
    when the caller does not pin a seed.

Because the simulator is procedural, the training pool is effectively unlimited
and disjoint from eval, so generalization (train-seeds -> held-out eval seeds)
is the thing being measured, not memorization.
"""

from __future__ import annotations

import os
import random
from typing import Any, Optional
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

from retailceo.environment import RetailCEOEnv
from retailceo.models import BenchmarkConfig, CEOObservation
from retailceo.prompts import parse_response, render_observation

# Support both in-repo and standalone (uvicorn server.app:app) imports.
try:
    from ..models import CEOTextAction, CEOTextObservation
except ImportError as e:
    if "relative import" not in str(e) and "no known parent package" not in str(e):
        raise
    from models import CEOTextAction, CEOTextObservation  # type: ignore


# Seeds used by the public benchmark protocols (lite 42-46, full 42-51).
# Reserved: the training env refuses these unless explicitly overridden.
RESERVED_EVAL_SEEDS: frozenset[int] = frozenset(range(42, 52))

# Training episodes are drawn from seeds >= this floor, disjoint from eval.
TRAIN_SEED_FLOOR: int = 100_000


class RetailCEOEnvironment(Environment):
    """OpenEnv-compatible RetailCEO training environment (text action)."""

    def __init__(
        self,
        difficulty: str = "medium",
        weeks: int = 12,
        horizon_years: int = 0,
        crisis_prob: float = 0.85,
        starting_cash_inr: float = 2e8,
        allow_eval_seeds: bool = False,
        token_budget: Optional[int] = None,
    ):
        super().__init__()
        self._difficulty = difficulty
        self._weeks = weeks
        self._horizon_years = horizon_years
        self._crisis_prob = crisis_prob
        self._starting_cash_inr = starting_cash_inr
        self._allow_eval_seeds = allow_eval_seeds
        self._token_budget = token_budget

        self._seed_rng = random.Random()
        self._env: Optional[RetailCEOEnv] = None
        self._obs: Optional[CEOObservation] = None
        self._state = State(episode_id=str(uuid4()), step_count=0)

    # ------------------------------------------------------------------
    # Config / seed policy
    # ------------------------------------------------------------------

    def _make_config(self) -> BenchmarkConfig:
        return BenchmarkConfig(
            weeks_per_quarter=self._weeks,
            horizon_years=self._horizon_years,
            difficulty=self._difficulty,
            crisis_prob=self._crisis_prob,
            starting_cash_inr=self._starting_cash_inr,
        )

    def _resolve_seed(self, seed: Optional[int]) -> int:
        if seed is None:
            # Draw a fresh training seed from the disjoint pool.
            return self._seed_rng.randint(TRAIN_SEED_FLOOR, 2**31 - 1)
        if seed in RESERVED_EVAL_SEEDS and not self._allow_eval_seeds:
            raise ValueError(
                f"Seed {seed} is a reserved benchmark eval seed "
                f"({min(RESERVED_EVAL_SEEDS)}-{max(RESERVED_EVAL_SEEDS)}). "
                "Training on it leaks the eval set. Pass allow_eval_seeds=True "
                "only for reproducing official leaderboard numbers, never for training."
            )
        return int(seed)

    # ------------------------------------------------------------------
    # OpenEnv interface
    # ------------------------------------------------------------------

    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs: Any,
    ) -> CEOTextObservation:
        resolved_seed = self._resolve_seed(seed)
        self._env = RetailCEOEnv(self._make_config())
        self._obs = self._env.reset(seed=resolved_seed)
        self._state = State(episode_id=episode_id or str(uuid4()), step_count=0)
        return self._to_observation(self._obs, parse_meta=None, seed=resolved_seed)

    def step(self, action: CEOTextAction) -> CEOTextObservation:  # type: ignore[override]
        if self._env is None or self._obs is None:
            raise RuntimeError("Environment not initialized. Call reset() first.")

        ceo_action, parse_tel = parse_response(action.completion, self._obs.inbox)
        next_obs = self._env.step(ceo_action)
        self._obs = next_obs
        self._state.step_count += 1
        return self._to_observation(next_obs, parse_meta=parse_tel)

    @property
    def state(self) -> State:
        return self._state

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _to_observation(
        self,
        obs: CEOObservation,
        parse_meta: Optional[dict],
        seed: Optional[int] = None,
    ) -> CEOTextObservation:
        max_weeks = self._env.MAX_WEEKS if self._env is not None else 0
        kpi = obs.kpi_snapshot
        metadata: dict[str, Any] = {
            "episode_id": self._state.episode_id,
            "step_count": self._state.step_count,
            "difficulty": self._difficulty,
        }
        if seed is not None:
            metadata["seed"] = seed
        if parse_meta is not None:
            metadata["parse"] = parse_meta

        return CEOTextObservation(
            done=obs.done,
            reward=obs.reward,
            metadata=metadata,
            prompt=render_observation(obs, token_budget=self._token_budget),
            week=obs.week_of_quarter,
            max_weeks=max_weeks,
            inbox_size=len(obs.inbox),
            ebitda_margin_pct=obs.pnl_snapshot.ebitda_margin_pct,
            cash_inr=kpi.cash_inr,
            stockout_rate_pct=kpi.stockout_rate_pct,
            nps=kpi.nps,
            revenue_inr=kpi.revenue_inr,
        )
