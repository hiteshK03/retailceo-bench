"""Crisis system tests — scheduling, activation, expiry, effects."""

import random

from retailceo import crises as CR
from retailceo import economics as E
from retailceo.models import CrisisEvent


class TestScheduleCrises:
    def test_returns_list(self):
        rng = random.Random(42)
        drifts = {"supply_chain": 0.2, "store_ops": 0.2, "finance": 0.1, "growth": 0.3}
        result = CR.schedule_crises(rng, crisis_prob=1.0, dept_drifts=drifts,
                                     cities=E.STARTING_CITIES, days_in_quarter=91)
        assert isinstance(result, list)
        assert all(isinstance(c, CrisisEvent) for c in result)

    def test_high_prob_schedules_crises(self):
        rng = random.Random(42)
        drifts = {"supply_chain": 0.2, "store_ops": 0.2, "finance": 0.1, "growth": 0.3}
        result = CR.schedule_crises(rng, crisis_prob=1.0, dept_drifts=drifts,
                                     cities=E.STARTING_CITIES, days_in_quarter=91)
        assert len(result) >= 1, "High crisis_prob should schedule at least 1 crisis"

    def test_zero_prob_no_crises(self):
        rng = random.Random(42)
        drifts = {"supply_chain": 0.2, "store_ops": 0.2, "finance": 0.1, "growth": 0.3}
        result = CR.schedule_crises(rng, crisis_prob=0.0, dept_drifts=drifts,
                                     cities=E.STARTING_CITIES, days_in_quarter=91)
        assert len(result) == 0

    def test_sorted_by_start_day(self):
        rng = random.Random(42)
        drifts = {"supply_chain": 0.2, "store_ops": 0.2, "finance": 0.1, "growth": 0.3}
        result = CR.schedule_crises(rng, crisis_prob=1.0, dept_drifts=drifts,
                                     cities=E.STARTING_CITIES, days_in_quarter=91)
        days = [c.started_day for c in result]
        assert days == sorted(days)

    def test_day_offset(self):
        rng = random.Random(42)
        drifts = {"supply_chain": 0.2, "store_ops": 0.2, "finance": 0.1, "growth": 0.3}
        result = CR.schedule_crises(rng, crisis_prob=1.0, dept_drifts=drifts,
                                     cities=E.STARTING_CITIES, days_in_quarter=91,
                                     day_offset=91)
        for c in result:
            assert c.started_day >= 91, f"Crisis should start after offset, got day {c.started_day}"

    def test_deterministic(self):
        drifts = {"supply_chain": 0.2, "store_ops": 0.2, "finance": 0.1, "growth": 0.3}
        r1 = CR.schedule_crises(random.Random(42), crisis_prob=1.0, dept_drifts=drifts,
                                 cities=E.STARTING_CITIES, days_in_quarter=91)
        r2 = CR.schedule_crises(random.Random(42), crisis_prob=1.0, dept_drifts=drifts,
                                 cities=E.STARTING_CITIES, days_in_quarter=91)
        assert len(r1) == len(r2)
        for c1, c2 in zip(r1, r2):
            assert c1.crisis_id == c2.crisis_id
            assert c1.started_day == c2.started_day
            assert c1.duration_days == c2.duration_days


class TestCrisisLifecycle:
    def _make_crisis(self, start=10, duration=5):
        return CrisisEvent(
            crisis_id="TEST",
            name="Test Crisis",
            started_day=start,
            duration_days=duration,
            severity="med",
        )

    def test_is_active(self):
        c = self._make_crisis(start=10, duration=5)
        assert not CR.is_active(c, 9)
        assert CR.is_active(c, 10)
        assert CR.is_active(c, 14)
        assert not CR.is_active(c, 15)

    def test_tick_firing(self):
        c = self._make_crisis(start=10, duration=5)
        queue = [c]
        firing, expired = CR.tick_crisis_active(queue, 10)
        assert c in firing
        assert len(expired) == 0
        assert c.active is True

    def test_tick_stays_active(self):
        c = self._make_crisis(start=10, duration=5)
        c.active = True
        queue = [c]
        firing, expired = CR.tick_crisis_active(queue, 12)
        assert len(firing) == 0
        assert len(expired) == 0
        assert c.active is True

    def test_tick_expiry(self):
        c = self._make_crisis(start=10, duration=5)
        c.active = True
        queue = [c]
        firing, expired = CR.tick_crisis_active(queue, 15)
        assert c in expired
        assert c.active is False

    def test_active_crises_now(self):
        c1 = self._make_crisis(start=5, duration=10)
        c1.active = True
        c2 = self._make_crisis(start=20, duration=5)
        c2.active = False
        assert CR.active_crises_now([c1, c2]) == [c1]

    def test_multiple_crises_lifecycle(self):
        c1 = self._make_crisis(start=5, duration=3)
        c2 = self._make_crisis(start=7, duration=4)
        queue = [c1, c2]

        CR.tick_crisis_active(queue, 5)
        assert c1.active and not c2.active

        CR.tick_crisis_active(queue, 7)
        assert c1.active and c2.active

        CR.tick_crisis_active(queue, 8)
        assert not c1.active and c2.active

        CR.tick_crisis_active(queue, 11)
        assert not c1.active and not c2.active


class TestCrisisEffects:
    def test_empty_list(self):
        effects = CR.crisis_effects_today([])
        assert effects["opex_bump_inr"] == 0.0
        assert effects["sla_mult"] == 1.0
        assert effects["nps_bump"] == 0.0

    def test_single_crisis_effects(self):
        c = CrisisEvent(
            crisis_id="C2",
            name="Monsoon",
            started_day=5,
            duration_days=7,
            severity="high",
            affected={
                "supply_mult": 0.55,
                "sla_mult": 0.70,
                "opex_bump_inr": 40000.0,
            },
            active=True,
        )
        effects = CR.crisis_effects_today([c])
        assert effects["opex_bump_inr"] == 40000.0
        assert effects["sla_mult"] == 0.70

    def test_multiple_crises_aggregate(self):
        c1 = CrisisEvent(
            crisis_id="C1", name="A", started_day=1, duration_days=5,
            severity="med", affected={"opex_bump_inr": 10000.0, "nps_bump": 1.0},
            active=True,
        )
        c2 = CrisisEvent(
            crisis_id="C2", name="B", started_day=1, duration_days=5,
            severity="med", affected={"opex_bump_inr": 20000.0, "nps_bump": -2.0, "sla_mult": 0.8},
            active=True,
        )
        effects = CR.crisis_effects_today([c1, c2])
        assert effects["opex_bump_inr"] == 30000.0
        assert effects["nps_bump"] == -1.0
        assert effects["sla_mult"] == 0.8


class TestCrisesStartingInHorizon:
    def test_finds_upcoming(self):
        c = CrisisEvent(
            crisis_id="C1", name="Diwali", started_day=10,
            duration_days=7, severity="high",
        )
        result = CR.crises_starting_in_horizon([c], week=1, horizon_weeks=2)
        assert c in result

    def test_ignores_past(self):
        c = CrisisEvent(
            crisis_id="C1", name="Diwali", started_day=3,
            duration_days=7, severity="high", active=True,
        )
        result = CR.crises_starting_in_horizon([c], week=2, horizon_weeks=1)
        assert c not in result

    def test_ignores_far_future(self):
        c = CrisisEvent(
            crisis_id="C1", name="Diwali", started_day=50,
            duration_days=7, severity="high",
        )
        result = CR.crises_starting_in_horizon([c], week=2, horizon_weeks=1)
        assert c not in result
