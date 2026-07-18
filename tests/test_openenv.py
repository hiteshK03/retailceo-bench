"""OpenEnv adapter tests — parity with the benchmark + train/eval seed split.

These run the adapter in-process (no HTTP) so they need only `openenv`
installed, which ships pydantic/fastapi. The parity test is the load-bearing
guarantee: driving the OpenEnv env with an approve-all *text* completion must
reproduce the exact reward the benchmark's own runner produces for the same
seed — i.e. the adapter is pure glue and changed no scoring.
"""

import json

import pytest

pytest.importorskip("openenv")

from retailceo.environment import RetailCEOEnv as CoreEnv
from retailceo.models import BenchmarkConfig, CEOAction, ProposalDecision
from retailceo_env.models import CEOTextAction, CEOTextObservation
from retailceo_env.server.retailceo_environment import (
    RESERVED_EVAL_SEEDS,
    TRAIN_SEED_FLOOR,
    RetailCEOEnvironment,
)


def _approve_all_completion(inbox_ids) -> str:
    """A well-formed <action> block approving every proposal in the inbox."""
    decisions = [{"proposal_id": pid, "verdict": "approve"} for pid in inbox_ids]
    payload = {"decisions": decisions, "budget_allocations": {}}
    return f"<action>\n{json.dumps(payload)}\n</action>"


def _core_approve_all_rewards(seed, weeks=12, difficulty="medium"):
    """Reference reward sequence straight from the core simulator."""
    env = CoreEnv(BenchmarkConfig(weeks_per_quarter=weeks, difficulty=difficulty))
    obs = env.reset(seed=seed)
    rewards = []
    while not obs.done:
        action = CEOAction(
            action_type="decide",
            decisions=[
                ProposalDecision(proposal_id=p.proposal_id, verdict="approve")
                for p in obs.inbox
            ],
        )
        obs = env.step(action)
        if obs.reward is not None:
            rewards.append(obs.reward)
    return rewards


class TestParity:
    """Text-action adapter must reproduce core-simulator rewards exactly."""

    def test_approve_all_reward_parity(self):
        seed = 123456  # a training-pool seed
        reference = _core_approve_all_rewards(seed)

        env = RetailCEOEnvironment(difficulty="medium", weeks=12)
        obs = env.reset(seed=seed)
        assert isinstance(obs, CEOTextObservation)
        assert obs.prompt  # non-empty rendered brief

        adapter_rewards = []
        while not obs.done:
            # Reconstruct inbox ids from the running core env (the adapter holds it).
            inbox_ids = [p.proposal_id for p in env._obs.inbox]
            completion = _approve_all_completion(inbox_ids)
            obs = env.step(CEOTextAction(completion=completion))
            if obs.reward is not None:
                adapter_rewards.append(obs.reward)

        assert adapter_rewards == pytest.approx(reference, rel=1e-12)

    def test_observation_scalars_populated(self):
        env = RetailCEOEnvironment(difficulty="easy", weeks=8)
        obs = env.reset(seed=200000)
        assert obs.week == 1
        assert obs.max_weeks == 8
        assert obs.inbox_size >= 1
        assert obs.cash_inr > 0

    def test_malformed_completion_falls_back(self):
        """Garbage text must degrade to request_info, not crash."""
        env = RetailCEOEnvironment(difficulty="medium", weeks=4)
        obs = env.reset(seed=200001)
        obs = env.step(CEOTextAction(completion="I refuse to answer in JSON."))
        # request_info is a no-op verdict → episode continues fine.
        assert obs.metadata["parse"]["parse_ok"] is False
        assert not obs.done or obs.reward is not None


class TestSeedSplit:
    """Reserved eval seeds must be refused for training by default."""

    def test_reserved_eval_seed_refused(self):
        env = RetailCEOEnvironment()
        for seed in (42, 46, 51):
            assert seed in RESERVED_EVAL_SEEDS
            with pytest.raises(ValueError, match="reserved benchmark eval seed"):
                env.reset(seed=seed)

    def test_eval_seed_allowed_with_override(self):
        env = RetailCEOEnvironment(allow_eval_seeds=True)
        obs = env.reset(seed=42)
        assert obs.week == 1

    def test_unpinned_seed_is_training_pool(self):
        env = RetailCEOEnvironment()
        obs = env.reset()  # no seed → drawn from training pool
        assert obs.metadata["seed"] >= TRAIN_SEED_FLOOR
        assert obs.metadata["seed"] not in RESERVED_EVAL_SEEDS

    def test_training_seed_matches_eval_episode_when_overridden(self):
        """Sanity: allow_eval_seeds reproduces the exact benchmark episode."""
        reference = _core_approve_all_rewards(42)
        env = RetailCEOEnvironment(allow_eval_seeds=True)
        obs = env.reset(seed=42)
        rewards = []
        while not obs.done:
            inbox_ids = [p.proposal_id for p in env._obs.inbox]
            obs = env.step(CEOTextAction(completion=_approve_all_completion(inbox_ids)))
            if obs.reward is not None:
                rewards.append(obs.reward)
        assert rewards == pytest.approx(reference, rel=1e-12)
