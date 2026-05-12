"""RetailCEO-Bench environment — tier-2 Indian retail simulation.

1 step = 1 week (7 daily ticks inside).
1 episode = configurable weeks (default 12) = 1 quarter.

Flow per step(action):
    1. Execute approved proposals (mutate ledger; buffer next-week multipliers)
    2. Consume pending weekly effects (revenue/margin/NPS multipliers)
    3. Tick 7 days:
         • competitor events (once at week start)
         • for each day: crisis activation → demand/supply/SLA → daily ledger tick
    4. Aggregate weekly KPIs, update NPS/basket/footfall/repeat
    5. Compute weekly reward (grader.weekly_reward)
    6. Record in state.history + cache next-week's inbox, crises, etc.
    7. Return the next-week's CEOObservation
"""

from __future__ import annotations

import random
import uuid
from typing import Any, Dict, List, Optional

from .models import (
    BenchmarkConfig,
    CEOAction,
    CEOObservation,
    CompanyLedger,
    CompetitorEvent,
    Complaint,
    CrisisEvent,
    EnvState,
    KPISnapshot,
    PnLSnapshot,
    Proposal,
    ProposalDecision,
    WeeklyDecision,
)
from . import crises as CR
from . import demand as DMD
from . import departments as DEP
from . import economics as E
from . import grader as GR
from . import ledger as LD


class RetailCEOEnv:
    """Standalone evaluation environment for RetailCEO-Bench."""

    def __init__(self, config: BenchmarkConfig | None = None):
        self.config = config or BenchmarkConfig()
        if self.config.horizon_years > 0:
            self.MAX_WEEKS: int = self.config.horizon_years * 52
        else:
            self.MAX_WEEKS: int = self.config.weeks_per_quarter
        self.DAYS_PER_QUARTER: int = 13 * E.DAYS_PER_WEEK
        self._multi_year: bool = self.config.horizon_years > 0

        self._rng: random.Random = random.Random(0)
        self._rng_seed: int = 0
        self._state: EnvState = EnvState()
        self._min_cash_reached: float = 0.0
        self._min_cash_quarter: float = 0.0
        self._current_quarter: int = 1
        self._cash_last_week: float = 0.0

        self._competitor_events_window: List[CompetitorEvent] = []
        self._pending_complaints: List[Complaint] = []
        self._last_journal_entry: str = ""
        self._last_kpi_snapshot: Optional[KPISnapshot] = None
        self._current_inbox: List[Proposal] = []
        self._current_active_crises: List[CrisisEvent] = []

    # -------------------------------------------------------------------
    # Reset
    # -------------------------------------------------------------------

    def reset(self, seed: Optional[int] = None) -> CEOObservation:
        self._rng_seed = (
            int(seed)
            if seed is not None
            else (
                int(self.config.seed)
                if self.config.seed is not None
                else random.randint(0, 2**31 - 1)
            )
        )
        self._rng = random.Random(self._rng_seed)

        ledger = LD.create_initial_ledger(self._rng, difficulty=self.config.difficulty)
        if self.config.starting_cash_inr != E.STARTING_CASH_INR:
            ledger.cash_inr = self.config.starting_cash_inr

        drifts = self._sample_drifts()

        crisis_queue = CR.schedule_crises(
            self._rng,
            crisis_prob=self.config.crisis_prob,
            dept_drifts=drifts,
            cities=ledger.cities,
            days_in_quarter=self.DAYS_PER_QUARTER,
        )

        self._state = EnvState(
            episode_id=str(uuid.uuid4()),
            day=0,
            week=0,
            rng_seed=self._rng_seed,
            company=ledger,
            dept_drifts=drifts,
            crisis_queue=crisis_queue,
            history=[],
        )

        self._competitor_events_window = []
        self._pending_complaints = []
        self._last_journal_entry = ""
        self._last_kpi_snapshot = KPISnapshot(
            revenue_inr=E.BASELINE_WEEKLY_REVENUE_INR,
            gross_margin_pct=E.STARTING_BLENDED_MARGIN_PCT,
            stockout_rate_pct=E.STARTING_STOCKOUT_PCT,
            nps=E.STARTING_NPS,
            cash_inr=ledger.cash_inr,
            shrinkage_pct=E.STARTING_SHRINKAGE_PCT,
            delivery_sla_hit_rate_pct=E.STARTING_SLA_HIT_RATE_PCT,
            basket_size_inr=E.STARTING_BASKET_SIZE_INR,
            footfall_per_store=E.STARTING_FOOTFALL_PER_STORE,
            repeat_purchase_rate_pct=E.STARTING_REPEAT_PURCHASE_PCT,
        )
        ledger.kpi_history.append(self._last_kpi_snapshot)
        self._min_cash_reached = ledger.cash_inr
        self._min_cash_quarter = ledger.cash_inr
        self._cash_last_week = ledger.cash_inr
        self._current_quarter = 1

        self._state.week = 1
        self._state.day = 0
        inbox = self._generate_weekly_inbox(week=1)
        self._current_inbox = inbox
        self._current_active_crises = []

        return self._build_observation(
            step_type="weekly_decision",
            week=1,
            inbox=inbox,
            reward=None,
            done=False,
            message=self._narrative_for_week(1, crisis_queue),
        )

    # -------------------------------------------------------------------
    # Step
    # -------------------------------------------------------------------

    def step(self, action: CEOAction) -> CEOObservation:
        ledger = self._state.company
        prev_week = self._state.week
        current_inbox = list(self._current_inbox)

        # 1. Execute approved/modified proposals
        LD.execute_approved_proposals(
            ledger, current_inbox, action.decisions, self._rng,
            week=prev_week, multi_year=self._multi_year,
        )

        # 2. Consume pending weekly effect buffer
        pending = LD.consume_pending_effects(ledger)
        pending_rev_mult = pending["revenue_mult"]
        pending_margin_delta = pending["margin_delta_pts"]
        pending_nps_delta = pending["nps_delta"]
        pending_sla_delta = pending["sla_delta_pts"]

        # 3. Run 7 daily ticks
        daily_tel_list: List[Dict[str, Any]] = []

        new_comp = DMD.competitor_weekly_events(ledger, prev_week, self._rng)
        self._competitor_events_window.extend(new_comp)
        self._competitor_events_window = [
            c for c in self._competitor_events_window if c.week >= prev_week - 3
        ]

        week_start_day = (prev_week - 1) * 7 + 1
        max_day = self.MAX_WEEKS * E.DAYS_PER_WEEK
        for offset in range(7):
            d = week_start_day + offset
            if d > max_day:
                break

            firing, expired = CR.tick_crisis_active(self._state.crisis_queue, d)
            active = CR.active_crises_now(self._state.crisis_queue)
            effects = CR.crisis_effects_today(active)

            for c in firing:
                cash_bump = float((c.affected or {}).get("cash_bump_inr", 0.0))
                if cash_bump != 0.0:
                    ledger.cash_inr += cash_bump

            share_drain = DMD.active_share_drain_pct(
                self._competitor_events_window, prev_week
            )
            share_drain = min(
                15.0,
                share_drain + float(effects.get("share_drain_bump_pct", 0.0)),
            )

            day_of_q = ((d - 1) % 91) + 1 if self._multi_year else d
            cat_demand = DMD.customer_daily_demand(
                ledger=ledger,
                day_of_quarter=day_of_q,
                nps=self._last_kpi_snapshot.nps,
                share_drain_pct=share_drain,
                active_crises=active,
                rng=self._rng,
                pending_revenue_mult=pending_rev_mult,
                episode_day=d if self._multi_year else None,
            )
            sla_hit = DMD.rider_daily_sla_hit_rate(d, active, self._rng)

            tel = LD.tick_one_day(
                ledger=ledger,
                day_of_quarter=d,
                category_demand_units=cat_demand,
                sla_hit_rate_pct=sla_hit,
                crisis_extra_opex_inr=float(effects.get("opex_bump_inr", 0.0)),
                rng=self._rng,
                cogs_mult_by_category=effects.get("cogs_mult_by_category") or None,
                payment_friction_pct=float(effects.get("payment_friction_pct", 0.0)),
            )
            daily_tel_list.append(tel)
            self._min_cash_reached = min(self._min_cash_reached, ledger.cash_inr)
            self._state.day = d

        # 4. Weekly KPI aggregation
        weekly_revenue = sum(t["revenue_inr"] for t in daily_tel_list)
        weekly_cogs = sum(t["cogs_inr"] for t in daily_tel_list)
        weekly_opex = sum(t["opex_inr"] for t in daily_tel_list)
        weekly_sla = (
            sum(t["sla_hit_rate_pct"] for t in daily_tel_list)
            / max(1, len(daily_tel_list))
        )
        weekly_stockout = (
            sum(t["stockout_rate_pct"] for t in daily_tel_list)
            / max(1, len(daily_tel_list))
        )
        weekly_shrinkage_value = sum(t["shrinkage_value_inr"] for t in daily_tel_list)
        weekly_shrinkage_pct = (
            weekly_shrinkage_value / max(1.0, weekly_revenue) * 100.0
            if weekly_revenue > 0
            else E.STARTING_SHRINKAGE_PCT
        )

        prev_nps = self._last_kpi_snapshot.nps
        high_sev_complaints = sum(
            1 for c in self._pending_complaints if c.severity == "high"
        )
        new_nps = DMD.update_weekly_nps(
            prev_nps=prev_nps,
            stockout_rate_pct=weekly_stockout,
            sla_hit_rate_pct=weekly_sla,
            pending_nps_delta=pending_nps_delta,
            high_severity_complaints=high_sev_complaints,
            rng=self._rng,
        )
        festival_weight = DMD.festival_weight_for_week(prev_week)
        new_basket = DMD.update_weekly_basket_size(
            self._last_kpi_snapshot.basket_size_inr,
            weekly_stockout,
            festival_weight,
            self._rng,
        )
        new_footfall = DMD.update_weekly_footfall(
            self._last_kpi_snapshot.footfall_per_store,
            DMD.active_share_drain_pct(
                self._competitor_events_window, prev_week
            ),
            festival_weight,
            weekly_stockout,
            self._rng,
        )
        new_repeat = DMD.update_weekly_repeat_purchase(
            self._last_kpi_snapshot.repeat_purchase_rate_pct,
            new_nps,
            pending_loyalty_boost=0.0,
            rng=self._rng,
        )

        snap = LD.snapshot_weekly_kpis(
            ledger=ledger,
            weekly_revenue=weekly_revenue,
            weekly_cogs=weekly_cogs,
            weekly_stockout_rate_pct=weekly_stockout,
            weekly_shrinkage_pct=weekly_shrinkage_pct,
            weekly_sla_hit_rate_pct=max(
                45.0, min(99.0, weekly_sla + pending_sla_delta)
            ),
            weekly_nps=new_nps,
            weekly_basket_inr=new_basket,
            weekly_footfall_per_store=new_footfall,
            weekly_repeat_purchase_pct=new_repeat,
        )
        snap.margin_delta_pts = snap.margin_delta_pts + pending_margin_delta
        self._last_kpi_snapshot = snap

        # 5. Weekly reward
        cash_this_week = ledger.cash_inr
        weekly_r, components = GR.weekly_reward(
            kpi_snapshot=snap,
            decisions=action.decisions,
            inbox=current_inbox,
            journal_entry=action.journal_entry,
            prev_journal_entry=self._last_journal_entry,
            cash_this_week=cash_this_week,
            cash_last_week=self._cash_last_week,
        )
        self._cash_last_week = cash_this_week
        self._last_journal_entry = action.journal_entry

        # 6. Record in history
        self._state.history.append(
            WeeklyDecision(
                week=prev_week,
                decisions=action.decisions,
                budget_allocations=action.budget_allocations,
                journal_entry=action.journal_entry,
                weekly_reward=weekly_r,
                reward_components={
                    k: v
                    for k, v in components.items()
                    if k.startswith("weighted.") or k == "total"
                },
                kpi_snapshot=snap,
            )
        )

        # 7. Generate franchise complaints for next week's observation
        stockout_by_cat = {"aggregate": weekly_stockout}
        self._pending_complaints = DMD.franchisee_weekly_complaints(
            ledger=ledger,
            week_of_quarter=prev_week + 1,
            stockout_rate_by_category=stockout_by_cat,
            sla_hit_rate_pct=weekly_sla,
            rng=self._rng,
        )

        # 8. Quarter-boundary logic (multi-year mode)
        next_week = prev_week + 1
        if self._multi_year and prev_week % 13 == 0 and next_week <= self.MAX_WEEKS:
            self._accumulate_pnl_into_ytd(ledger)
            ledger.pnl_qtd = PnLSnapshot()
            self._min_cash_quarter = ledger.cash_inr
            self._current_quarter += 1

            if self._current_quarter % 4 == 1 and self._current_quarter > 1:
                self._accumulate_ytd_into_lifetime(ledger)
                ledger.pnl_ytd = PnLSnapshot()

            day_offset = prev_week * 7
            new_crises = CR.schedule_crises(
                self._rng,
                crisis_prob=self.config.crisis_prob,
                dept_drifts=self._state.dept_drifts,
                cities=ledger.cities,
                days_in_quarter=13 * E.DAYS_PER_WEEK,
                day_offset=day_offset,
            )
            self._state.crisis_queue.extend(new_crises)

            q_r, _ = GR.quarterly_scorecard(ledger, self._min_cash_quarter)
            weekly_r += q_r

        # 9. Determine next week / terminal
        done = next_week > self.MAX_WEEKS
        self._state.week = next_week if not done else prev_week

        if done:
            if self._multi_year:
                self._accumulate_pnl_into_ytd(ledger)
            term_r, term_components = GR.terminal_reward(
                ledger, self._min_cash_reached
            )
            total_reward = weekly_r + term_r
            self._current_inbox = []
            self._current_active_crises = CR.active_crises_now(
                self._state.crisis_queue
            )
            return self._build_observation(
                step_type="quarterly_close",
                week=prev_week,
                inbox=[],
                reward=total_reward,
                done=True,
                message=self._terminal_narrative(ledger),
            )

        inbox_next = self._generate_weekly_inbox(next_week)
        self._current_inbox = inbox_next
        self._current_active_crises = CR.active_crises_now(
            self._state.crisis_queue
        )

        return self._build_observation(
            step_type="weekly_decision",
            week=next_week,
            inbox=inbox_next,
            reward=weekly_r,
            done=False,
            message=self._narrative_for_week(
                next_week, self._state.crisis_queue
            ),
        )

    # -------------------------------------------------------------------
    # State + close
    # -------------------------------------------------------------------

    @property
    def state(self) -> EnvState:
        return self._state

    def close(self) -> None:
        pass

    # -------------------------------------------------------------------
    # Drift sampling
    # -------------------------------------------------------------------

    def _sample_drifts(self) -> Dict[str, float]:
        difficulty = self.config.difficulty
        base_map = E.DIFFICULTY_DRIFT_MAP.get(difficulty, E.DIFFICULTY_DRIFT_MAP["medium"])
        jitter = E.DIFFICULTY_DRIFT_JITTER.get(difficulty, 0.05)
        drifts: Dict[str, float] = {}
        for dept, base in base_map.items():
            drifts[dept] = max(
                0.0,
                min(1.0, base + self._rng.uniform(-jitter, jitter)),
            )
        return drifts

    # -------------------------------------------------------------------
    # Inbox generation
    # -------------------------------------------------------------------

    def _generate_weekly_inbox(self, week: int) -> List[Proposal]:
        active_crises = CR.active_crises_now(self._state.crisis_queue)
        return DEP.generate_weekly_proposals(
            ledger=self._state.company,
            active_crises=active_crises,
            week=week,
            dept_drifts=self._state.dept_drifts,
            rng=self._rng,
            crisis_queue=self._state.crisis_queue,
        )

    # -------------------------------------------------------------------
    # Observation builder
    # -------------------------------------------------------------------

    def _build_observation(
        self,
        step_type: str,
        week: int,
        inbox: List[Proposal],
        reward: Optional[float],
        done: bool,
        message: str,
    ) -> CEOObservation:
        active = CR.active_crises_now(self._state.crisis_queue)
        return CEOObservation(
            done=done,
            reward=reward,
            step_type=step_type,
            day_of_quarter=self._state.day,
            week_of_quarter=week,
            kpi_snapshot=self._last_kpi_snapshot or KPISnapshot(),
            pnl_snapshot=self._state.company.pnl_qtd,
            inbox=inbox,
            active_crises=active,
            franchise_complaints=list(self._pending_complaints),
            competitor_events=list(self._competitor_events_window),
            last_journal=self._last_journal_entry,
            task_description=self._task_description(week, active),
            message=message,
        )

    # -------------------------------------------------------------------
    # Narrative helpers
    # -------------------------------------------------------------------

    def _task_description(
        self, week: int, active: List[CrisisEvent]
    ) -> str:
        head = (
            f"Week {week}/{self.MAX_WEEKS} of RetailCEO's festive quarter "
            f"in tier-2 India."
        )
        if active:
            crisis_names = ", ".join(
                f"{c.crisis_id} {c.name}" for c in active
            )
            return (
                f"{head} Currently active: {crisis_names}. "
                f"Review the inbox and decide."
            )
        return (
            f"{head} Review the inbox, decide per proposal, "
            f"allocate budget, log the journal."
        )

    def _narrative_for_week(
        self,
        week: int,
        crisis_queue: List[CrisisEvent],
    ) -> str:
        upcoming = [
            c
            for c in crisis_queue
            if c.started_day > self._state.day
            and c.started_day <= self._state.day + 14
            and not c.active
        ]
        bits = [f"Week {week} begins."]
        if upcoming:
            bits.append(
                "On the horizon: "
                + ", ".join(
                    f"{c.name} (~day {c.started_day})" for c in upcoming[:2]
                )
                + "."
            )
        return " ".join(bits)

    @staticmethod
    def _accumulate_pnl_into_ytd(ledger: CompanyLedger) -> None:
        ytd = ledger.pnl_ytd
        qtd = ledger.pnl_qtd
        ytd.revenue_qtd_inr += qtd.revenue_qtd_inr
        ytd.cogs_qtd_inr += qtd.cogs_qtd_inr
        ytd.opex_qtd_inr += qtd.opex_qtd_inr
        ytd.ebitda_qtd_inr += qtd.ebitda_qtd_inr
        ytd.cash_delta_qtd_inr += qtd.cash_delta_qtd_inr
        rev = ytd.revenue_qtd_inr
        ytd.ebitda_margin_pct = (ytd.ebitda_qtd_inr / rev * 100.0) if rev else 0.0

    @staticmethod
    def _accumulate_ytd_into_lifetime(ledger: CompanyLedger) -> None:
        lt = ledger.pnl_lifetime
        ytd = ledger.pnl_ytd
        lt.revenue_qtd_inr += ytd.revenue_qtd_inr
        lt.cogs_qtd_inr += ytd.cogs_qtd_inr
        lt.opex_qtd_inr += ytd.opex_qtd_inr
        lt.ebitda_qtd_inr += ytd.ebitda_qtd_inr
        lt.cash_delta_qtd_inr += ytd.cash_delta_qtd_inr
        rev = lt.revenue_qtd_inr
        lt.ebitda_margin_pct = (lt.ebitda_qtd_inr / rev * 100.0) if rev else 0.0

    def _terminal_narrative(self, ledger: CompanyLedger) -> str:
        pnl = ledger.pnl_qtd
        return (
            f"Quarter closed. Revenue ₹{pnl.revenue_qtd_inr/1e7:.2f} Cr, "
            f"EBITDA ₹{pnl.ebitda_qtd_inr/1e7:+.2f} Cr "
            f"({pnl.ebitda_margin_pct:+.1f}%), "
            f"final cash ₹{ledger.cash_inr/1e7:+.2f} Cr, "
            f"min cash reached ₹{self._min_cash_reached/1e7:+.2f} Cr."
        )
