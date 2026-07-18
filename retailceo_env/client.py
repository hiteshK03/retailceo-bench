"""Client for the RetailCEO OpenEnv environment.

Trainers import this and drive the env over HTTP/WebSocket, framework-agnostic:

    from retailceo_env import RetailCEOEnv, CEOTextAction

    with RetailCEOEnv(base_url="http://localhost:8000") as env:
        result = env.reset(seed=123456)          # training seed (>= 100000)
        while not result.done:
            prompt = result.observation.prompt   # feed to your model
            completion = my_model.generate(prompt)
            result = env.step(CEOTextAction(completion=completion))
            reward = result.reward               # per-week reward (terminal on last)

Or start the container automatically:

    env = RetailCEOEnv.from_docker_image("retailceo-env:latest")
"""

from __future__ import annotations

from typing import Any, Dict

from openenv.core.client_types import StepResult
from openenv.core.env_client import EnvClient
from openenv.core.env_server.types import State

from .models import CEOTextAction, CEOTextObservation


class RetailCEOEnv(EnvClient[CEOTextAction, CEOTextObservation, State]):
    """HTTP/WebSocket client for the RetailCEO environment server."""

    def _step_payload(self, action: CEOTextAction) -> Dict:
        return {"completion": action.completion}

    def _parse_result(self, payload: Dict) -> StepResult[CEOTextObservation]:
        obs_data = payload.get("observation", {}) or {}
        observation = CEOTextObservation(
            prompt=obs_data.get("prompt", ""),
            week=obs_data.get("week", 0),
            max_weeks=obs_data.get("max_weeks", 0),
            inbox_size=obs_data.get("inbox_size", 0),
            ebitda_margin_pct=obs_data.get("ebitda_margin_pct", 0.0),
            cash_inr=obs_data.get("cash_inr", 0.0),
            stockout_rate_pct=obs_data.get("stockout_rate_pct", 0.0),
            nps=obs_data.get("nps", 0.0),
            revenue_inr=obs_data.get("revenue_inr", 0.0),
            done=payload.get("done", obs_data.get("done", False)),
            reward=payload.get("reward", obs_data.get("reward")),
            metadata=payload.get("metadata", obs_data.get("metadata", {})),
        )
        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
            metadata=payload.get("metadata"),
        )

    def _parse_state(self, payload: Dict) -> State:
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
