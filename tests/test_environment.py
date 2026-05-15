"""Deterministic replay, step count, terminal checks for RetailCEOEnv."""

import random

import pytest

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


class TestCrossPlatformReproducibility:
    """Hardcoded reference values from seed=42, medium, 12-week episodes.

    Uses rel=1e-9 tolerance to accommodate x86 vs ARM64 FP rounding
    (last 1-2 ULPs).  Still far tighter than anything that matters for
    benchmark scoring.  If a code change shifts values beyond this
    tolerance, update deliberately — it means simulation logic changed.
    """

    REL_TOL = 1e-9

    REFERENCE_REWARDS_APPROVE_ALL = [
        0.18959924431096092,
        0.16641171332456312,
        0.1591459305645289,
        0.035726311581812914,
        0.09431754170239083,
        0.14944267684219548,
        0.008214262017846474,
        0.1297427197586753,
        0.1464766275819625,
        0.058628553427330796,
        -0.1384369408794115,
        0.15726234825287463,
    ]
    REFERENCE_TOTAL_REWARD_APPROVE_ALL = 1.1565309884857302
    REFERENCE_FINAL_CASH_APPROVE_ALL = 581198796.6654339
    REFERENCE_EBITDA_MARGIN_APPROVE_ALL = -0.46476598618603904

    REFERENCE_REWARDS_REJECT_ALL = [
        0.1769278191144848,
        -0.012024532754634186,
        -0.16222580783034818,
        -0.213745601117238,
        -0.1594090404327218,
        -0.16166563984502058,
        -0.16914775530546328,
        -0.22408618059988594,
        -0.210219135770829,
        -0.2449339065372373,
        -0.26136173273945007,
        -0.6825410687199475,
    ]
    REFERENCE_TOTAL_REWARD_REJECT_ALL = -2.324432582538291
    REFERENCE_FINAL_CASH_REJECT_ALL = 433881859.189679

    def _run_episode(self, policy_fn, seed=42, weeks=12, difficulty="medium"):
        cfg = BenchmarkConfig(weeks_per_quarter=weeks, difficulty=difficulty)
        env = RetailCEOEnv(cfg)
        obs = env.reset(seed=seed)
        rewards = []
        while not obs.done:
            obs = env.step(policy_fn(obs))
            if obs.reward is not None:
                rewards.append(obs.reward)
        return rewards, env.state.company.cash_inr, env.state.company.pnl_qtd.ebitda_margin_pct

    def test_approve_all_rewards(self):
        rewards, _, _ = self._run_episode(_approve_all)
        assert rewards == pytest.approx(self.REFERENCE_REWARDS_APPROVE_ALL, rel=self.REL_TOL)

    def test_approve_all_total_reward(self):
        rewards, _, _ = self._run_episode(_approve_all)
        assert sum(rewards) == pytest.approx(self.REFERENCE_TOTAL_REWARD_APPROVE_ALL, rel=self.REL_TOL)

    def test_approve_all_final_cash(self):
        _, cash, _ = self._run_episode(_approve_all)
        assert cash == pytest.approx(self.REFERENCE_FINAL_CASH_APPROVE_ALL, rel=self.REL_TOL)

    def test_approve_all_ebitda_margin(self):
        _, _, margin = self._run_episode(_approve_all)
        assert margin == pytest.approx(self.REFERENCE_EBITDA_MARGIN_APPROVE_ALL, rel=self.REL_TOL)

    def test_reject_all_rewards(self):
        rewards, cash, _ = self._run_episode(_reject_all)
        assert rewards == pytest.approx(self.REFERENCE_REWARDS_REJECT_ALL, rel=self.REL_TOL)
        assert cash == pytest.approx(self.REFERENCE_FINAL_CASH_REJECT_ALL, rel=self.REL_TOL)

    def test_reject_all_total_reward(self):
        rewards, _, _ = self._run_episode(_reject_all)
        assert sum(rewards) == pytest.approx(self.REFERENCE_TOTAL_REWARD_REJECT_ALL, rel=self.REL_TOL)


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
