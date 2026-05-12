"""RetailCEO-Bench pydantic models.

Adapted from SimMart models. Rogue/fraud types removed.
Renamed: CEOAction, CEOObservation, EnvState.
Added: BenchmarkConfig for configurable episodes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


DEPTS: tuple[str, ...] = (
    "supply_chain",
    "store_ops",
    "finance",
    "growth",
)

VERDICTS: tuple[str, ...] = (
    "approve",
    "reject",
    "modify",
    "request_info",
)

ACTION_TYPES: tuple[str, ...] = ("decide", "journal", "noop")

STEP_TYPES: tuple[str, ...] = (
    "weekly_decision",
    "daily_update",
    "quarterly_close",
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class BenchmarkConfig(BaseModel):
    """Configurable episode parameters."""

    weeks_per_quarter: int = Field(default=12, description="Episode length in weeks")
    horizon_years: int = Field(
        default=0,
        description="0 = use weeks_per_quarter (backward compat), 1/3/5 = multi-year",
    )
    difficulty: str = Field(
        default="medium",
        description="Difficulty level: 'easy' | 'medium' | 'hard' — controls dept drift",
    )
    crisis_prob: float = Field(default=0.85, description="Probability of each crisis type firing")
    starting_cash_inr: float = Field(default=2e8, description="Starting cash (default ₹20 Cr)")
    seed: Optional[int] = Field(default=None, description="Global seed override")


# ---------------------------------------------------------------------------
# Leaf types
# ---------------------------------------------------------------------------

class ProposalDecision(BaseModel):
    """CEO's verdict on a single proposal."""

    proposal_id: str = Field(..., description="Matches a Proposal.proposal_id from the inbox")
    verdict: str = Field(..., description=f"One of {VERDICTS}")
    modified_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="If verdict == 'modify', the params that override the original proposal",
    )
    reasoning: str = Field(default="", description="Short per-decision rationale")


class Proposal(BaseModel):
    """A single weekly proposal from a department to the CEO."""

    proposal_id: str = Field(..., description="e.g. 'S-07' (supply_chain, week-7 running index)")
    dept: str = Field(..., description=f"One of {DEPTS}")
    action: str = Field(
        ...,
        description="Action namespace.action — e.g. 'po.place', 'staff.schedule', 'campaign.launch'",
    )
    params: Dict[str, Any] = Field(default_factory=dict, description="Action-specific fields")
    cost_inr: float = Field(
        default=0.0,
        description="Estimated signed ₹ impact (negative = cost, positive = revenue/recovery)",
    )
    urgency: str = Field(default="med", description="low | med | high")
    reasoning: str = Field(default="", description="Department's free-text justification")
    week_submitted: int = Field(default=0, description="Simulation week this proposal was filed")


class CrisisEvent(BaseModel):
    """A crisis event (Diwali surge, monsoon flood, competitor entry)."""

    crisis_id: str = Field(..., description="C1..C3")
    name: str = Field(..., description="Human-readable name")
    started_day: int = Field(..., description="Day-of-quarter the crisis begins")
    duration_days: int = Field(..., description="Scheduled duration")
    severity: str = Field(default="med", description="low | med | high")
    affected: Dict[str, Any] = Field(default_factory=dict)
    active: bool = Field(default=False)
    description: str = Field(default="", description="Narrative for CEO-facing observation")


class Complaint(BaseModel):
    """A franchisee complaint."""

    franchise_id: str
    city: str
    issue: str
    severity: str = Field(default="med", description="low | med | high")
    week_filed: int


class CompetitorEvent(BaseModel):
    """A competitor-driven event."""

    competitor: str = Field(..., description="JioMart | Blinkit | Zepto | DMart | Reliance Fresh")
    event_type: str = Field(
        ...,
        description="price_cut | city_entry | dark_store_open | loyalty_push | bulk_ad",
    )
    region: str = Field(default="")
    impact_pct: float = Field(default=0.0, description="Estimated share impact %")
    week: int = Field(default=0)
    description: str = Field(default="")


class KPISnapshot(BaseModel):
    """Weekly KPIs (absolutes + deltas vs prior week)."""

    revenue_inr: float = 0.0
    gross_margin_pct: float = 0.0
    stockout_rate_pct: float = 0.0
    nps: float = 0.0
    cash_inr: float = 0.0
    shrinkage_pct: float = 0.0
    delivery_sla_hit_rate_pct: float = 0.0
    basket_size_inr: float = 0.0
    footfall_per_store: float = 0.0
    repeat_purchase_rate_pct: float = 0.0

    revenue_delta_pct: float = 0.0
    margin_delta_pts: float = 0.0
    stockout_delta_pts: float = 0.0
    nps_delta: float = 0.0
    sla_delta_pts: float = 0.0

    cash_delta_inr: float = 0.0
    cash_burn_rate_inr_per_week: float = 0.0
    cash_runway_weeks: Optional[float] = None
    cash_pressure_score: float = 0.0
    cash_pressure_streak_weeks: int = 0


class PnLSnapshot(BaseModel):
    """Quarter-to-date P&L."""

    revenue_qtd_inr: float = 0.0
    cogs_qtd_inr: float = 0.0
    opex_qtd_inr: float = 0.0
    ebitda_qtd_inr: float = 0.0
    ebitda_margin_pct: float = 0.0
    cash_delta_qtd_inr: float = 0.0


class CompanyLedger(BaseModel):
    """Company-wide mutable state."""

    cash_inr: float = Field(default=0.0)
    line_of_credit_limit: float = Field(default=0.0)
    line_of_credit_drawn: float = Field(default=0.0)

    inventory: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    stores: List[Dict[str, Any]] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    franchisees: List[Dict[str, Any]] = Field(default_factory=list)
    sku_catalogue: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    kpi_history: List[KPISnapshot] = Field(default_factory=list)
    pnl_qtd: PnLSnapshot = Field(default_factory=PnLSnapshot)
    pnl_ytd: PnLSnapshot = Field(default_factory=PnLSnapshot)
    pnl_lifetime: PnLSnapshot = Field(default_factory=PnLSnapshot)

    cogs_factor: float = Field(default=1.0, description="Difficulty-based COGS discount")
    growth_lever_mult: float = Field(default=1.0, description="Difficulty-based growth amplification")


class WeeklyDecision(BaseModel):
    """Audit record of the CEO's action + environment response that week."""

    week: int
    decisions: List[ProposalDecision] = Field(default_factory=list)
    budget_allocations: Dict[str, float] = Field(default_factory=dict)
    journal_entry: str = ""
    weekly_reward: float = 0.0
    reward_components: Dict[str, float] = Field(default_factory=dict)
    kpi_snapshot: Optional[KPISnapshot] = None


# ---------------------------------------------------------------------------
# Contract types
# ---------------------------------------------------------------------------

class CEOAction(BaseModel):
    """CEO's weekly action: decisions + budget + journal."""

    action_type: str = Field(default="decide", description=f"One of {ACTION_TYPES}")
    decisions: List[ProposalDecision] = Field(default_factory=list)
    budget_allocations: Dict[str, float] = Field(default_factory=dict)
    journal_entry: str = Field(default="")


class CEOObservation(BaseModel):
    """Weekly observation presented to the CEO."""

    step_type: str = Field(default="weekly_decision", description=f"One of {STEP_TYPES}")
    day_of_quarter: int = Field(default=0)
    week_of_quarter: int = Field(default=0)

    kpi_snapshot: KPISnapshot = Field(default_factory=KPISnapshot)
    pnl_snapshot: PnLSnapshot = Field(default_factory=PnLSnapshot)

    inbox: List[Proposal] = Field(default_factory=list)
    active_crises: List[CrisisEvent] = Field(default_factory=list)
    franchise_complaints: List[Complaint] = Field(default_factory=list)
    competitor_events: List[CompetitorEvent] = Field(default_factory=list)

    last_journal: str = Field(default="")
    task_description: str = Field(default="")
    message: str = Field(default="")

    reward: Optional[float] = Field(default=None)
    done: bool = Field(default=False)


class EnvState(BaseModel):
    """Internal environment state."""

    episode_id: str = Field(default="")
    day: int = Field(default=0)
    week: int = Field(default=0)
    rng_seed: int = Field(default=0)

    company: CompanyLedger = Field(default_factory=CompanyLedger)

    dept_drifts: Dict[str, float] = Field(
        default_factory=dict,
        description="Per-dept alignment parameter in [0,1]; higher = more self-serving",
    )

    crisis_queue: List[CrisisEvent] = Field(default_factory=list)
    history: List[WeeklyDecision] = Field(default_factory=list)
