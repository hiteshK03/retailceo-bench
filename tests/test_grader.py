"""Reward computation tests — component isolation and bounds."""

from retailceo import economics as E
from retailceo.grader import (
    cash_floor_penalty,
    cash_pressure_penalty,
    free_cash_flow_score,
    kpi_delta_score,
    quarterly_pnl_bonus,
    stockout_penalty,
    terminal_reward,
    weekly_reward,
)
from retailceo.models import CompanyLedger, KPISnapshot, PnLSnapshot


def _baseline_kpi(**overrides):
    defaults = dict(
        revenue_inr=E.BASELINE_WEEKLY_REVENUE_INR,
        gross_margin_pct=E.STARTING_BLENDED_MARGIN_PCT,
        stockout_rate_pct=E.STARTING_STOCKOUT_PCT,
        nps=E.STARTING_NPS,
        cash_inr=E.STARTING_CASH_INR,
        delivery_sla_hit_rate_pct=E.STARTING_SLA_HIT_RATE_PCT,
        basket_size_inr=E.STARTING_BASKET_SIZE_INR,
        footfall_per_store=E.STARTING_FOOTFALL_PER_STORE,
        repeat_purchase_rate_pct=E.STARTING_REPEAT_PURCHASE_PCT,
    )
    defaults.update(overrides)
    return KPISnapshot(**defaults)


class TestKPIDeltaScore:
    """kpi_delta_score should be 0 at baseline and respond to changes."""

    def test_baseline_is_zero(self):
        score = kpi_delta_score(_baseline_kpi())
        assert abs(score) < 0.01, f"Baseline KPI score should be ~0, got {score}"

    def test_improved_kpis_positive(self):
        kpi = _baseline_kpi(
            revenue_inr=E.BASELINE_WEEKLY_REVENUE_INR * 1.2,
            nps=45,
            stockout_rate_pct=2.0,
        )
        assert kpi_delta_score(kpi) > 0

    def test_degraded_kpis_negative(self):
        kpi = _baseline_kpi(
            revenue_inr=E.BASELINE_WEEKLY_REVENUE_INR * 0.7,
            nps=15,
            stockout_rate_pct=20.0,
        )
        assert kpi_delta_score(kpi) < 0

    def test_score_bounded(self):
        best = _baseline_kpi(
            revenue_inr=1e9,
            gross_margin_pct=50,
            stockout_rate_pct=0,
            nps=100,
            delivery_sla_hit_rate_pct=100,
        )
        worst = _baseline_kpi(
            revenue_inr=0,
            gross_margin_pct=-20,
            stockout_rate_pct=100,
            nps=-50,
            delivery_sla_hit_rate_pct=0,
        )
        assert -1.0 <= kpi_delta_score(best) <= 1.0
        assert -1.0 <= kpi_delta_score(worst) <= 1.0


class TestStockoutPenalty:
    def test_no_penalty_below_threshold(self):
        assert stockout_penalty(_baseline_kpi(stockout_rate_pct=3.0)) == 0.0
        assert stockout_penalty(_baseline_kpi(stockout_rate_pct=5.0)) == 0.0

    def test_penalty_above_threshold(self):
        p = stockout_penalty(_baseline_kpi(stockout_rate_pct=10.0))
        assert p > 0

    def test_penalty_capped_at_one(self):
        assert stockout_penalty(_baseline_kpi(stockout_rate_pct=100.0)) == 1.0

    def test_penalty_proportional(self):
        p10 = stockout_penalty(_baseline_kpi(stockout_rate_pct=10.0))
        p20 = stockout_penalty(_baseline_kpi(stockout_rate_pct=20.0))
        assert p20 > p10


class TestCashPressurePenalty:
    def test_no_pressure_at_starting_cash(self):
        kpi = _baseline_kpi(cash_inr=E.STARTING_CASH_INR)
        assert cash_pressure_penalty(kpi) == 0.0

    def test_pressure_when_cash_low(self):
        kpi = _baseline_kpi(cash_inr=E.STARTING_CASH_INR * 0.3)
        assert cash_pressure_penalty(kpi) > 0

    def test_uses_cash_pressure_score_when_set(self):
        kpi = _baseline_kpi(cash_pressure_score=0.75)
        assert cash_pressure_penalty(kpi) == 0.75


class TestCashFloorPenalty:
    def test_no_penalty_above_threshold(self):
        assert cash_floor_penalty(E.STARTING_CASH_INR) == 0.0
        assert cash_floor_penalty(E.STARTING_CASH_INR * 0.6) == 0.0

    def test_penalty_below_threshold(self):
        p = cash_floor_penalty(E.STARTING_CASH_INR * 0.3)
        assert 0 < p < 1.0

    def test_max_penalty_at_zero(self):
        assert cash_floor_penalty(0.0) == 1.0

    def test_max_penalty_below_zero(self):
        assert cash_floor_penalty(-1e7) == 1.0

    def test_no_penalty_at_half(self):
        assert cash_floor_penalty(E.STARTING_CASH_INR * 0.50) == 0.0


class TestQuarterlyPnlBonus:
    def test_breakeven_at_negative_three(self):
        ledger = CompanyLedger(pnl_qtd=PnLSnapshot(ebitda_margin_pct=-3.0))
        assert abs(quarterly_pnl_bonus(ledger)) < 0.01

    def test_positive_margin_positive_bonus(self):
        ledger = CompanyLedger(pnl_qtd=PnLSnapshot(ebitda_margin_pct=5.0))
        assert quarterly_pnl_bonus(ledger) > 0

    def test_deep_loss_negative(self):
        ledger = CompanyLedger(pnl_qtd=PnLSnapshot(ebitda_margin_pct=-10.0))
        assert quarterly_pnl_bonus(ledger) < 0

    def test_bounded(self):
        for margin in (-50, -13, -3, 0, 7, 20, 50):
            ledger = CompanyLedger(pnl_qtd=PnLSnapshot(ebitda_margin_pct=margin))
            assert -1.0 <= quarterly_pnl_bonus(ledger) <= 1.0


class TestFreeCashFlowScore:
    def test_positive_cash_generation(self):
        assert free_cash_flow_score(25e7, 20e7) > 0

    def test_cash_burn(self):
        assert free_cash_flow_score(15e7, 20e7) < 0

    def test_no_change(self):
        assert free_cash_flow_score(20e7, 20e7) == 0.0

    def test_bounded(self):
        assert -1.0 <= free_cash_flow_score(0, 1e9) <= 1.0
        assert -1.0 <= free_cash_flow_score(1e9, 0) <= 1.0


class TestWeeklyReward:
    def test_returns_tuple(self):
        total, components = weekly_reward(
            kpi_snapshot=_baseline_kpi(),
            decisions=[],
            inbox=[],
            journal_entry="",
        )
        assert isinstance(total, float)
        assert isinstance(components, dict)
        assert "total" in components

    def test_baseline_near_zero(self):
        total, _ = weekly_reward(
            kpi_snapshot=_baseline_kpi(),
            decisions=[],
            inbox=[],
            journal_entry="",
        )
        assert abs(total) < 0.15, f"Baseline weekly reward should be near 0, got {total}"

    def test_components_present(self):
        _, components = weekly_reward(
            kpi_snapshot=_baseline_kpi(),
            decisions=[],
            inbox=[],
            journal_entry="",
        )
        assert "weighted.kpi_delta" in components
        assert "weighted.stockout" in components
        assert "weighted.cash_pressure" in components
        assert "weighted.false_reject" in components

    def test_false_reject_penalizes_high_urgency_rejects(self):
        """Rejecting high-urgency proposals must lower reward vs approving them."""
        inbox = [
            Proposal(proposal_id="S-1", dept="supply_chain", action="po.place", urgency="high"),
            Proposal(proposal_id="S-2", dept="supply_chain", action="po.place", urgency="high"),
        ]
        approve = [ProposalDecision(proposal_id=p.proposal_id, verdict="approve") for p in inbox]
        reject = [ProposalDecision(proposal_id=p.proposal_id, verdict="reject") for p in inbox]
        r_approve, _ = weekly_reward(_baseline_kpi(), approve, inbox, "")
        r_reject, comp = weekly_reward(_baseline_kpi(), reject, inbox, "")
        assert r_reject < r_approve
        assert comp["raw.false_reject"] > 0.0

    def test_false_reject_ignores_low_urgency(self):
        """Low-urgency rejects (typical of self-serving padding) barely penalized."""
        inbox = [
            Proposal(proposal_id="G-1", dept="growth", action="discount.run", urgency="low")
            for _ in range(1)
        ]
        reject = [ProposalDecision(proposal_id="G-1", verdict="reject")]
        _, comp = weekly_reward(_baseline_kpi(), reject, inbox, "")
        assert comp["raw.false_reject"] <= 0.1


class TestTerminalReward:
    def test_returns_tuple(self):
        ledger = CompanyLedger(pnl_qtd=PnLSnapshot(ebitda_margin_pct=5.0))
        total, components = terminal_reward(ledger, E.STARTING_CASH_INR)
        assert isinstance(total, float)
        assert "total" in components

    def test_positive_for_profitable_safe_company(self):
        ledger = CompanyLedger(pnl_qtd=PnLSnapshot(ebitda_margin_pct=5.0))
        total, _ = terminal_reward(ledger, E.STARTING_CASH_INR)
        assert total > 0

    def test_negative_for_loss_making_cash_poor(self):
        ledger = CompanyLedger(pnl_qtd=PnLSnapshot(ebitda_margin_pct=-10.0))
        total, _ = terminal_reward(ledger, 1e6)
        assert total < 0


class TestRewardBounds:
    """Verify reward stays within theoretical bounds over a full episode."""

    def test_total_reward_bounded(self):
        from retailceo.environment import RetailCEOEnv
        from retailceo.models import BenchmarkConfig

        for seed in (42, 99, 123):
            env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=12, difficulty="medium"))
            obs = env.reset(seed=seed)
            total = 0.0
            while not obs.done:
                action = CEOAction(
                    action_type="decide",
                    decisions=[
                        ProposalDecision(
                            proposal_id=p.proposal_id,
                            verdict="approve",
                            reasoning="ok",
                        )
                        for p in obs.inbox
                    ],
                )
                obs = env.step(action)
                if obs.reward is not None:
                    total += obs.reward
            assert -6.0 <= total <= 5.0, f"Total reward {total} out of bounds (seed={seed})"


from retailceo.models import CEOAction, Proposal, ProposalDecision
