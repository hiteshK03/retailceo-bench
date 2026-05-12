"""Demand pipeline tests — NPS dynamics, competitor effects, festival weights."""

import random

from retailceo import demand as DMD
from retailceo import economics as E
from retailceo import ledger as LD
from retailceo.models import CompetitorEvent, CrisisEvent


def _fresh_ledger(seed=42):
    rng = random.Random(seed)
    return LD.create_initial_ledger(rng, difficulty="medium"), rng


class TestCustomerDailyDemand:
    def test_returns_dict_with_categories(self):
        ledger, rng = _fresh_ledger()
        result = DMD.customer_daily_demand(
            ledger=ledger,
            day_of_quarter=1,
            nps=35.0,
            share_drain_pct=0.0,
            active_crises=[],
            rng=rng,
        )
        assert isinstance(result, dict)
        assert len(result) > 0
        for cat, units in result.items():
            assert units >= 0, f"Negative demand for {cat}: {units}"

    def test_positive_demand(self):
        ledger, rng = _fresh_ledger()
        result = DMD.customer_daily_demand(
            ledger=ledger, day_of_quarter=1, nps=35.0,
            share_drain_pct=0.0, active_crises=[], rng=rng,
        )
        total = sum(result.values())
        assert total > 0

    def test_share_drain_reduces_demand(self):
        ledger, rng1 = _fresh_ledger(seed=42)
        d_no_drain = DMD.customer_daily_demand(
            ledger=ledger, day_of_quarter=1, nps=35.0,
            share_drain_pct=0.0, active_crises=[], rng=rng1,
        )

        ledger2, rng2 = _fresh_ledger(seed=42)
        d_with_drain = DMD.customer_daily_demand(
            ledger=ledger2, day_of_quarter=1, nps=35.0,
            share_drain_pct=10.0, active_crises=[], rng=rng2,
        )
        assert sum(d_with_drain.values()) < sum(d_no_drain.values())

    def test_low_nps_reduces_demand(self):
        ledger1, rng1 = _fresh_ledger(seed=42)
        d_high = DMD.customer_daily_demand(
            ledger=ledger1, day_of_quarter=1, nps=50.0,
            share_drain_pct=0.0, active_crises=[], rng=rng1,
        )

        ledger2, rng2 = _fresh_ledger(seed=42)
        d_low = DMD.customer_daily_demand(
            ledger=ledger2, day_of_quarter=1, nps=10.0,
            share_drain_pct=0.0, active_crises=[], rng=rng2,
        )
        assert sum(d_low.values()) < sum(d_high.values())


class TestCompetitorEvents:
    def test_returns_list(self):
        ledger, rng = _fresh_ledger()
        events = DMD.competitor_weekly_events(ledger, week_of_quarter=1, rng=rng)
        assert isinstance(events, list)
        for e in events:
            assert isinstance(e, CompetitorEvent)

    def test_events_have_fields(self):
        ledger, rng = _fresh_ledger()
        events = DMD.competitor_weekly_events(ledger, week_of_quarter=1, rng=rng)
        for e in events:
            assert e.competitor != ""
            assert e.event_type != ""


class TestShareDrain:
    def test_no_events_no_drain(self):
        assert DMD.active_share_drain_pct([], current_week=5) == 0.0

    def test_recent_events_drain(self):
        events = [
            CompetitorEvent(
                competitor="JioMart", event_type="city_entry",
                impact_pct=5.0, week=4,
            ),
        ]
        drain = DMD.active_share_drain_pct(events, current_week=5)
        assert drain > 0

    def test_old_events_decay(self):
        events = [
            CompetitorEvent(
                competitor="JioMart", event_type="city_entry",
                impact_pct=5.0, week=1,
            ),
        ]
        drain_close = DMD.active_share_drain_pct(events, current_week=2)
        drain_far = DMD.active_share_drain_pct(events, current_week=10)
        assert drain_far < drain_close

    def test_drain_capped(self):
        events = [
            CompetitorEvent(
                competitor=f"Comp{i}", event_type="city_entry",
                impact_pct=10.0, week=5,
            )
            for i in range(20)
        ]
        drain = DMD.active_share_drain_pct(events, current_week=5)
        assert drain <= 15.0


class TestNPSUpdate:
    def test_stable_at_baseline(self):
        rng = random.Random(42)
        nps = DMD.update_weekly_nps(
            prev_nps=E.STARTING_NPS,
            stockout_rate_pct=E.STARTING_STOCKOUT_PCT,
            sla_hit_rate_pct=E.STARTING_SLA_HIT_RATE_PCT,
            pending_nps_delta=0.0,
            high_severity_complaints=0,
            rng=rng,
        )
        assert abs(nps - E.STARTING_NPS) < 5.0, f"NPS should be near baseline, got {nps}"

    def test_high_stockout_drops_nps(self):
        rng = random.Random(42)
        nps = DMD.update_weekly_nps(
            prev_nps=E.STARTING_NPS,
            stockout_rate_pct=25.0,
            sla_hit_rate_pct=60.0,
            pending_nps_delta=0.0,
            high_severity_complaints=5,
            rng=rng,
        )
        assert nps < E.STARTING_NPS

    def test_nps_bounded(self):
        rng = random.Random(42)
        nps_low = DMD.update_weekly_nps(
            prev_nps=-90, stockout_rate_pct=50.0,
            sla_hit_rate_pct=10.0, pending_nps_delta=-20.0,
            high_severity_complaints=10, rng=rng,
        )
        assert nps_low >= -100

        rng2 = random.Random(42)
        nps_high = DMD.update_weekly_nps(
            prev_nps=95, stockout_rate_pct=0.0,
            sla_hit_rate_pct=100.0, pending_nps_delta=20.0,
            high_severity_complaints=0, rng=rng2,
        )
        assert nps_high <= 100


class TestBasketAndFootfall:
    def test_basket_positive(self):
        rng = random.Random(42)
        basket = DMD.update_weekly_basket_size(
            prev_basket_inr=450.0, stockout_rate_pct=5.0,
            festival_weight=1.0, rng=rng,
        )
        assert basket > 0

    def test_footfall_positive(self):
        rng = random.Random(42)
        footfall = DMD.update_weekly_footfall(
            prev_footfall=500.0, share_drain_pct=0.0,
            festival_weight=1.0, stockout_rate_pct=5.0,
            rng=rng,
        )
        assert footfall > 0

    def test_festival_boosts_basket(self):
        rng1 = random.Random(42)
        basket_normal = DMD.update_weekly_basket_size(
            prev_basket_inr=450.0, stockout_rate_pct=5.0,
            festival_weight=1.0, rng=rng1,
        )
        rng2 = random.Random(42)
        basket_festival = DMD.update_weekly_basket_size(
            prev_basket_inr=450.0, stockout_rate_pct=5.0,
            festival_weight=2.0, rng=rng2,
        )
        assert basket_festival > basket_normal


class TestFranchiseeComplaints:
    def test_returns_list(self):
        ledger, rng = _fresh_ledger()
        complaints = DMD.franchisee_weekly_complaints(
            ledger=ledger, week_of_quarter=2,
            stockout_rate_by_category={"aggregate": 5.0},
            sla_hit_rate_pct=90.0, rng=rng,
        )
        assert isinstance(complaints, list)

    def test_high_stockout_more_complaints(self):
        ledger, rng1 = _fresh_ledger(seed=42)
        low = DMD.franchisee_weekly_complaints(
            ledger=ledger, week_of_quarter=2,
            stockout_rate_by_category={"aggregate": 2.0},
            sla_hit_rate_pct=95.0, rng=rng1,
        )
        ledger2, rng2 = _fresh_ledger(seed=42)
        high = DMD.franchisee_weekly_complaints(
            ledger=ledger2, week_of_quarter=2,
            stockout_rate_by_category={"aggregate": 25.0},
            sla_hit_rate_pct=50.0, rng=rng2,
        )
        assert len(high) >= len(low)
