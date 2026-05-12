"""Deterministic replay, step count, terminal checks for RetailCEOEnv."""

import random

from retailceo.environment import RetailCEOEnv
from retailceo.models import BenchmarkConfig, CEOAction, ProposalDecision


def _approve_all(obs):
    decisions = [
        ProposalDecision(proposal_id=p.proposal_id, verdict="approve", reasoning="ok")
        for p in obs.inbox
    ]
    return CEOAction(action_type="decide", decisions=decisions)


def _reject_all(obs):
    decisions = [
        ProposalDecision(proposal_id=p.proposal_id, verdict="reject", reasoning="no")
        for p in obs.inbox
    ]
    return CEOAction(action_type="decide", decisions=decisions)


class TestDeterministicReplay:
    """Two runs with the same seed must produce identical rewards."""

    def _run_episode(self, seed, weeks=8, difficulty="easy"):
        cfg = BenchmarkConfig(weeks_per_quarter=weeks, difficulty=difficulty)
        env = RetailCEOEnv(cfg)
        obs = env.reset(seed=seed)
        rewards = []
        while not obs.done:
            obs = env.step(_approve_all(obs))
            if obs.reward is not None:
                rewards.append(obs.reward)
        return rewards, env.state.company.cash_inr

    def test_same_seed_same_rewards(self):
        r1, c1 = self._run_episode(seed=42)
        r2, c2 = self._run_episode(seed=42)
        assert r1 == r2, f"Reward sequences differ: {r1} vs {r2}"
        assert c1 == c2, f"Final cash differs: {c1} vs {c2}"

    def test_different_seeds_differ(self):
        r1, _ = self._run_episode(seed=42)
        r2, _ = self._run_episode(seed=99)
        assert r1 != r2, "Different seeds should produce different reward sequences"

    def test_determinism_across_difficulties(self):
        for diff in ("easy", "medium", "hard"):
            r1, _ = self._run_episode(seed=7, difficulty=diff)
            r2, _ = self._run_episode(seed=7, difficulty=diff)
            assert r1 == r2, f"Non-deterministic on {diff}: {r1} vs {r2}"


class TestStepCount:
    """Episode length matches config."""

    def test_default_12_weeks(self):
        env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=12, difficulty="easy"))
        obs = env.reset(seed=1)
        steps = 0
        while not obs.done:
            obs = env.step(_approve_all(obs))
            steps += 1
        assert steps == 12, f"Expected 12 steps, got {steps}"

    def test_custom_weeks(self):
        for weeks in (4, 8, 13, 26):
            env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=weeks, difficulty="easy"))
            obs = env.reset(seed=2)
            steps = 0
            while not obs.done:
                obs = env.step(_approve_all(obs))
                steps += 1
            assert steps == weeks, f"Expected {weeks} steps, got {steps}"

    def test_multi_year(self):
        env = RetailCEOEnv(BenchmarkConfig(horizon_years=1, difficulty="easy"))
        obs = env.reset(seed=3)
        steps = 0
        while not obs.done:
            obs = env.step(_approve_all(obs))
            steps += 1
        assert steps == 52, f"Expected 52 steps for 1 year, got {steps}"


class TestTerminal:
    """Terminal observation properties."""

    def test_done_flag_and_step_type(self):
        env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=4, difficulty="easy"))
        obs = env.reset(seed=10)
        for _ in range(3):
            obs = env.step(_approve_all(obs))
            assert not obs.done
        obs = env.step(_approve_all(obs))
        assert obs.done
        assert obs.step_type == "quarterly_close"

    def test_terminal_has_reward(self):
        env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=4, difficulty="easy"))
        obs = env.reset(seed=10)
        while not obs.done:
            obs = env.step(_approve_all(obs))
        assert obs.reward is not None

    def test_terminal_inbox_empty(self):
        env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=4, difficulty="easy"))
        obs = env.reset(seed=10)
        while not obs.done:
            obs = env.step(_approve_all(obs))
        assert obs.inbox == []


class TestObservation:
    """Observation structure validation."""

    def test_initial_observation(self):
        env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=8, difficulty="easy"))
        obs = env.reset(seed=42)
        assert obs.step_type == "weekly_decision"
        assert obs.week_of_quarter == 1
        assert not obs.done
        assert obs.reward is None
        assert len(obs.inbox) >= 1

    def test_inbox_size_bounds(self):
        env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=12, difficulty="medium"))
        obs = env.reset(seed=42)
        for _ in range(11):
            assert 4 <= len(obs.inbox) <= 16, f"Inbox size {len(obs.inbox)} out of expected range"
            obs = env.step(_approve_all(obs))

    def test_kpi_snapshot_populated(self):
        env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=4, difficulty="easy"))
        obs = env.reset(seed=42)
        obs = env.step(_approve_all(obs))
        snap = obs.kpi_snapshot
        assert snap.revenue_inr > 0
        assert snap.cash_inr > 0
        assert 0 <= snap.stockout_rate_pct <= 100
        assert -100 <= snap.nps <= 100
