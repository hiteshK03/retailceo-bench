"""RetailCEO-Bench economic constants — pure data, no logic.

Ported from SimMart economics.py.  Changes:
    • Episode length is configurable (default 12 weeks / 84 days)
    • DIFFICULTY_DRIFT_MAP replaces single DEPT_BASE_DRIFT + curriculum
    • Rogue constants removed entirely
    • Curriculum phases removed (evaluation, not training)

All ₹ values are floats in rupees (not lakhs/crores).
1 lakh = 1e5, 1 crore = 1e7.
"""

from __future__ import annotations

from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Episode scale (defaults; overridden by BenchmarkConfig at runtime)
# ---------------------------------------------------------------------------

DAYS_PER_WEEK: int = 7
DEFAULT_WEEKS_PER_QUARTER: int = 12
DEFAULT_DAYS_PER_QUARTER: int = DEFAULT_WEEKS_PER_QUARTER * DAYS_PER_WEEK  # 84


# ---------------------------------------------------------------------------
# Cities and stores (Apna-Mart-shaped; Central/East India tier-2)
# ---------------------------------------------------------------------------

STARTING_CITIES: List[str] = [
    "Ranchi",        # HQ (Jharkhand)
    "Jamshedpur",
    "Dhanbad",
    "Hazaribagh",
    "Raipur",        # Chhattisgarh
    "Bilaspur",
    "Asansol",       # West Bengal
    "Siliguri",
]

STORES_PER_CITY: Dict[str, int] = {
    "Ranchi": 20,
    "Jamshedpur": 15,
    "Dhanbad": 12,
    "Hazaribagh": 10,
    "Raipur": 14,
    "Bilaspur": 10,
    "Asansol": 12,
    "Siliguri": 7,
}

TOTAL_STARTING_STORES: int = sum(STORES_PER_CITY.values())  # 100

EXPANSION_TARGET_CITIES: List[str] = [
    "Bokaro", "Rourkela", "Durgapur", "Kharagpur", "Sambalpur",
    "Korba", "Gaya", "Muzaffarpur", "Patna", "Cuttack",
]


# ---------------------------------------------------------------------------
# KPI starting values
# ---------------------------------------------------------------------------

STARTING_CASH_INR: float = 20e7                  # ₹20 Cr
STARTING_LINE_OF_CREDIT_LIMIT_INR: float = 35e7  # ₹35 Cr
STARTING_NPS: float = 35.0
STARTING_STOCKOUT_PCT: float = 5.0
STARTING_SHRINKAGE_PCT: float = 2.0
STARTING_BLENDED_MARGIN_PCT: float = 13.0
STARTING_SLA_HIT_RATE_PCT: float = 90.0
STARTING_BASKET_SIZE_INR: float = 450.0
STARTING_FOOTFALL_PER_STORE: float = 500.0
STARTING_REPEAT_PURCHASE_PCT: float = 45.0
STARTING_RETURN_RATE_PCT: float = 1.0

NPS_RECOVERY_RATE: float = 0.30
CRISIS_INTENSITY_SCALE: float = 0.65

INITIAL_INVENTORY_DAYS_STAPLE: int = 21
INITIAL_INVENTORY_DAYS_PERISHABLE: int = 12
RESTOCK_TARGET_DAYS_STAPLE: int = 14
RESTOCK_TARGET_DAYS_PERISHABLE: int = 10
MAX_CRITICAL_RESTOCKS_PER_WEEK: int = 4


# ---------------------------------------------------------------------------
# Baseline P&L (per week, before CEO actions and seasonal effects)
# ---------------------------------------------------------------------------

BASELINE_WEEKLY_REVENUE_INR: float = 5.0e7   # ₹5 Cr
BASELINE_WEEKLY_COGS_INR: float = 4.35e7     # 87% COGS → 13% blended margin
BASELINE_WEEKLY_OPEX_INR: float = 5.0e6      # ₹50 L/wk
BASELINE_WEEKLY_EBITDA_INR: float = (
    BASELINE_WEEKLY_REVENUE_INR - BASELINE_WEEKLY_COGS_INR - BASELINE_WEEKLY_OPEX_INR
)


# ---------------------------------------------------------------------------
# Categories & margins
# ---------------------------------------------------------------------------

CATEGORY_MARGIN_PCT: Dict[str, float] = {
    "grocery_staple": 5.0,
    "fmcg": 15.0,
    "fresh": 20.0,
    "personal_care": 18.0,
    "household": 12.0,
    "packaged": 16.0,
    "seasonal": 25.0,
}

CATEGORY_NET_MARGIN_AFTER_SPOILAGE: Dict[str, float] = {
    "grocery_staple": 5.0,
    "fmcg": 15.0,
    "fresh": 15.0,
    "personal_care": 18.0,
    "household": 12.0,
    "packaged": 16.0,
    "seasonal": 22.0,
}

CATEGORY_PERISHABLE: Dict[str, bool] = {
    "grocery_staple": False,
    "fmcg": False,
    "fresh": True,
    "personal_care": False,
    "household": False,
    "packaged": False,
    "seasonal": False,
}

CATEGORY_REVENUE_SHARE: Dict[str, float] = {
    "grocery_staple": 0.42,
    "fmcg":           0.20,
    "fresh":          0.30,
    "household":      0.08,
}

CATEGORY_BASELINE_UNITS_PER_STORE_PER_DAY: Dict[str, float] = {}  # populated below


# ---------------------------------------------------------------------------
# SKU catalogue (8 representative SKUs)
# ---------------------------------------------------------------------------

def _margin_pct(price: float, cost: float) -> float:
    return round((price - cost) / price * 100.0, 2) if price > 0 else 0.0


SKU_CATALOGUE: Dict[str, Dict] = {
    "wheat-flour-5kg":   {"name": "Whole Wheat Flour 5kg","category": "grocery_staple", "price_inr": 235, "cost_inr": 223, "unit": "bag"},
    "rice-basmati-1kg":  {"name": "Basmati Rice 1kg",     "category": "grocery_staple", "price_inr": 140, "cost_inr": 133, "unit": "kg"},
    "oil-sunflower-1l":  {"name": "Sunflower Oil 1L",     "category": "grocery_staple", "price_inr": 155, "cost_inr": 147, "unit": "bottle"},
    "soap-lifebuoy":     {"name": "Lifebuoy Soap 125g",   "category": "fmcg",           "price_inr":  40, "cost_inr":  34, "unit": "bar"},
    "detergent-1kg":     {"name": "Surf Excel 1kg",       "category": "fmcg",           "price_inr": 210, "cost_inr": 178, "unit": "packet"},
    "milk-500ml":        {"name": "Amul Milk 500ml",      "category": "fresh",          "price_inr":  30, "cost_inr":  24, "unit": "pouch"},
    "bread-loaf":        {"name": "Britannia Bread 400g", "category": "fresh",          "price_inr":  50, "cost_inr":  40, "unit": "loaf"},
    "batteries-aa-4":    {"name": "AA Batteries 4-pack",  "category": "household",      "price_inr":  85, "cost_inr":  75, "unit": "pack"},
}


def _derive_baseline_units_per_store_per_day() -> Dict[str, float]:
    out: Dict[str, float] = {}
    baseline_daily_rev = BASELINE_WEEKLY_REVENUE_INR / 7.0
    for cat, share in CATEGORY_REVENUE_SHARE.items():
        prices = [v["price_inr"] for v in SKU_CATALOGUE.values() if v["category"] == cat]
        avg_price = sum(prices) / len(prices) if prices else 100.0
        cat_units = (baseline_daily_rev * share) / max(1.0, avg_price)
        out[cat] = cat_units / max(1, TOTAL_STARTING_STORES)
    return out


CATEGORY_BASELINE_UNITS_PER_STORE_PER_DAY = _derive_baseline_units_per_store_per_day()


# ---------------------------------------------------------------------------
# Festival calendar — day-of-quarter → festival event
#
# Quarter modelled on Oct–Dec (Indian festive season). Days 1-indexed.
# Events beyond episode length are simply never reached.
# ---------------------------------------------------------------------------

FESTIVAL_CALENDAR: Dict[int, Dict] = {
    # Dussehra (mid-quarter buildup)
    25: {"name": "Dussehra",       "demand_mult": 1.25, "categories": ["grocery_staple", "seasonal", "packaged"], "regions": ["ALL"]},
    26: {"name": "Dussehra peak",  "demand_mult": 1.35, "categories": ["grocery_staple", "seasonal", "packaged"], "regions": ["ALL"]},

    # Dhanteras + Diwali
    58: {"name": "Dhanteras",      "demand_mult": 1.6,  "categories": ["seasonal", "household", "fmcg"],                   "regions": ["ALL"]},
    60: {"name": "Diwali pre-peak","demand_mult": 1.9,  "categories": ["grocery_staple", "seasonal", "fmcg", "packaged"],  "regions": ["ALL"]},
    62: {"name": "Diwali",         "demand_mult": 2.4,  "categories": ["grocery_staple", "seasonal", "fmcg"],              "regions": ["ALL"]},
    63: {"name": "Diwali day+1",   "demand_mult": 1.6,  "categories": ["seasonal", "fresh"],                               "regions": ["ALL"]},
    64: {"name": "Bhai Dooj",      "demand_mult": 1.4,  "categories": ["seasonal", "grocery_staple"],                      "regions": ["ALL"]},

    # Post-Diwali correction
    66: {"name": "Post-Diwali trough", "demand_mult": 0.75, "categories": ["seasonal", "grocery_staple"], "regions": ["ALL"]},
    67: {"name": "Post-Diwali trough", "demand_mult": 0.78, "categories": ["seasonal", "grocery_staple"], "regions": ["ALL"]},

    # Chhath (HUGE in Bihar/Jharkhand → Ranchi HQ catchment)
    70: {"name": "Chhath pre-peak","demand_mult": 1.5,  "categories": ["grocery_staple", "fresh", "seasonal"], "regions": ["Ranchi", "Hazaribagh", "Dhanbad", "Jamshedpur"]},
    72: {"name": "Chhath peak",    "demand_mult": 1.9,  "categories": ["grocery_staple", "fresh", "seasonal"], "regions": ["Ranchi", "Hazaribagh", "Dhanbad", "Jamshedpur"]},
    73: {"name": "Chhath day+1",   "demand_mult": 1.3,  "categories": ["fresh", "grocery_staple"],            "regions": ["Ranchi", "Hazaribagh", "Dhanbad", "Jamshedpur"]},

    # Christmas / New Year
    83: {"name": "Christmas week", "demand_mult": 1.25, "categories": ["seasonal", "packaged", "personal_care"], "regions": ["ALL"]},
    85: {"name": "Christmas day",  "demand_mult": 1.3,  "categories": ["seasonal", "fresh"],                     "regions": ["ALL"]},
    89: {"name": "New Year Eve",   "demand_mult": 1.4,  "categories": ["packaged", "seasonal", "fmcg"],          "regions": ["ALL"]},
    90: {"name": "New Year Day",   "demand_mult": 1.2,  "categories": ["fresh", "packaged"],                     "regions": ["ALL"]},
}


# ---------------------------------------------------------------------------
# Salary cycle
# ---------------------------------------------------------------------------

def salary_cycle_multiplier(day_of_quarter: int) -> float:
    """Footfall multiplier in [0.85, 1.30] based on day-of-month."""
    day_of_month = ((day_of_quarter - 1) % 30) + 1
    if day_of_month in (1, 2):
        return 1.30
    if day_of_month in (3, 4):
        return 1.20
    if 5 <= day_of_month <= 7:
        return 1.08
    if 8 <= day_of_month <= 14:
        return 1.00
    if 15 <= day_of_month <= 20:
        return 0.85
    if 21 <= day_of_month <= 24:
        return 0.95
    if 25 <= day_of_month <= 28:
        return 1.10
    if 29 <= day_of_month <= 30:
        return 1.15
    return 1.00


# ---------------------------------------------------------------------------
# Monsoon
# ---------------------------------------------------------------------------

MONSOON_DAMPENER_DEFAULT_RANGE: Tuple[int, int] = (1, 12)
MONSOON_SUPPLY_DAMPENER: float = 0.85
MONSOON_SLA_DAMPENER: float = 0.80


# ---------------------------------------------------------------------------
# Reward weights
# ---------------------------------------------------------------------------

REWARD_WEIGHTS: Dict[str, float] = {
    "weekly_kpi_delta":   0.25,
    "weekly_fcf":         0.10,
    "quarterly_pnl":      0.70,
    "stockout":          -0.05,
    "cash_pressure":     -0.05,
    "cash_floor":        -0.40,
}

KPI_TARGETS: Dict[str, float] = {
    "revenue_inr":                 BASELINE_WEEKLY_REVENUE_INR,
    "gross_margin_pct":            STARTING_BLENDED_MARGIN_PCT,
    "stockout_rate_pct":           STARTING_STOCKOUT_PCT,
    "nps":                         STARTING_NPS,
    "delivery_sla_hit_rate_pct":   STARTING_SLA_HIT_RATE_PCT,
}

KPI_LEVEL_NORMALISERS: Dict[str, float] = {
    "revenue_inr":                 2.0e7,
    "gross_margin_pct":            5.0,
    "stockout_rate_pct":          10.0,
    "nps":                        15.0,
    "delivery_sla_hit_rate_pct":  10.0,
}

STOCKOUT_PER_PT_PENALTY: float = 0.05
CASH_FLOOR_TERMINAL_PENALTY: float = 1.0

CASH_BURN_WARN_PCT_OF_STARTING_CASH: float = 0.05
CASH_BURN_CRITICAL_PCT_OF_STARTING_CASH: float = 0.10
CASH_BURN_LOOKBACK_WEEKS: int = 4
CASH_RUNWAY_WARN_WEEKS: float = 6.0
CASH_PRESSURE_PERSISTENCE_WEEKS: int = 2


# ---------------------------------------------------------------------------
# Difficulty → dept drift mapping (replaces curriculum + single DEPT_BASE_DRIFT)
# ---------------------------------------------------------------------------

DIFFICULTY_DRIFT_MAP: Dict[str, Dict[str, float]] = {
    "easy":   {"supply_chain": 0.05, "store_ops": 0.05, "finance": 0.05, "growth": 0.05},
    "medium": {"supply_chain": 0.25, "store_ops": 0.20, "finance": 0.15, "growth": 0.30},
    "hard":   {"supply_chain": 0.75, "store_ops": 0.70, "finance": 0.60, "growth": 0.85},
}

DIFFICULTY_DRIFT_JITTER: Dict[str, float] = {
    "easy":   0.00,
    "medium": 0.05,
    "hard":   0.10,
}

# Per-difficulty COGS discount — models better supplier terms at lower difficulty.
# Applied as a multiplier on cost_inr at sell time: effective_cogs = cogs * factor.
#   easy:   0.90 → ~22% blended margin (comfortable profitability)
#   medium: 0.95 → ~18% blended margin (tight but viable with good management)
#   hard:   1.00 → ~13% blended margin (razor-thin, survival challenge)
DIFFICULTY_COGS_FACTOR: Dict[str, float] = {
    "easy":   0.90,
    "medium": 0.95,
    "hard":   1.00,
}

# Per-difficulty growth lever amplification — how much impact campaigns, promos,
# loyalty programs have on revenue/NPS.
#   easy:   1.5x (CEO decisions clearly move the needle)
#   medium: 1.2x (moderate payoff for smart growth investment)
#   hard:   1.0x (baseline — growth levers are weak, survival-focused)
DIFFICULTY_GROWTH_LEVER_MULT: Dict[str, float] = {
    "easy":   1.5,
    "medium": 1.2,
    "hard":   1.0,
}

# Festival-campaign synergy: campaigns launched during festival weeks get a
# bonus multiplier on their revenue effect.  Rewards timing-aware LLMs.
FESTIVAL_CAMPAIGN_SYNERGY_MULT: float = 1.8

# Strategic opportunities — rare high-ROI proposals that appear once every
# ~8-12 weeks.  An LLM that recognizes and approves these can dramatically
# outperform a heuristic baseline.
STRATEGIC_OPP_PROB_PER_WEEK: float = 0.10   # ~10% per week ≈ once per 10 weeks
STRATEGIC_OPP_REVENUE_MULT_RANGE: Tuple[float, float] = (1.15, 1.40)
STRATEGIC_OPP_DURATION_WEEKS_RANGE: Tuple[int, int] = (3, 6)

DEPT_DEFAULT_WEEKLY_BUDGET_INR: Dict[str, float] = {
    "supply_chain": 0.55 * BASELINE_WEEKLY_OPEX_INR,
    "store_ops":    0.20 * BASELINE_WEEKLY_OPEX_INR,
    "finance":      0.10 * BASELINE_WEEKLY_OPEX_INR,
    "growth":       0.15 * BASELINE_WEEKLY_OPEX_INR,
}


# ---------------------------------------------------------------------------
# Inbox sizing
# ---------------------------------------------------------------------------

INBOX_SIZE_MIN: int = 6
INBOX_SIZE_MAX: int = 12
INBOX_SIZE_MEAN: int = 9


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------

def starting_sku_ids() -> List[str]:
    return list(SKU_CATALOGUE.keys())


def skus_in_category(category: str) -> List[str]:
    return [sku_id for sku_id, sku in SKU_CATALOGUE.items() if sku["category"] == category]


def sku_margin_pct(sku_id: str) -> float:
    sku = SKU_CATALOGUE[sku_id]
    return _margin_pct(sku["price_inr"], sku["cost_inr"])


def festival_for_day(day_of_quarter: int) -> Dict | None:
    return FESTIVAL_CALENDAR.get(day_of_quarter)


# ---------------------------------------------------------------------------
# Year-aware festival calendar for multi-year episodes
# ---------------------------------------------------------------------------

ANNUAL_FESTIVAL_CALENDAR: Dict[int, Dict] = {
    # Pongal (Jan 14-15)
    14: {"name": "Pongal",           "demand_mult": 1.3,  "categories": ["grocery_staple", "fresh", "seasonal"], "regions": ["ALL"]},
    15: {"name": "Pongal day+1",     "demand_mult": 1.15, "categories": ["grocery_staple", "fresh"],             "regions": ["ALL"]},
    # Republic Day (Jan 26)
    26: {"name": "Republic Day",     "demand_mult": 1.1,  "categories": ["seasonal", "packaged"],                "regions": ["ALL"]},
    # Holi (~Mar 21)
    80: {"name": "Holi pre-peak",    "demand_mult": 1.4,  "categories": ["fmcg", "seasonal", "packaged"],        "regions": ["ALL"]},
    81: {"name": "Holi",             "demand_mult": 1.6,  "categories": ["fmcg", "seasonal", "packaged"],        "regions": ["ALL"]},
    82: {"name": "Holi day+1",       "demand_mult": 1.2,  "categories": ["fmcg", "fresh"],                       "regions": ["ALL"]},
    # Eid (~Apr 10, approximate — shifts annually but we fix for simulation)
    100: {"name": "Eid pre-peak",    "demand_mult": 1.5,  "categories": ["grocery_staple", "fresh", "fmcg"],     "regions": ["ALL"]},
    101: {"name": "Eid",             "demand_mult": 1.7,  "categories": ["grocery_staple", "fresh", "fmcg"],     "regions": ["ALL"]},
    102: {"name": "Eid day+1",       "demand_mult": 1.3,  "categories": ["fresh", "grocery_staple"],             "regions": ["ALL"]},
    # Independence Day (Aug 15)
    227: {"name": "Independence Day","demand_mult": 1.1,  "categories": ["seasonal", "packaged"],                "regions": ["ALL"]},
    # Raksha Bandhan (~Aug 18)
    230: {"name": "Raksha Bandhan",  "demand_mult": 1.35, "categories": ["seasonal", "fmcg", "packaged"],        "regions": ["ALL"]},
    231: {"name": "Raksha Bandhan+1","demand_mult": 1.15, "categories": ["seasonal"],                            "regions": ["ALL"]},
    # Onam (~Sep 2)
    245: {"name": "Onam pre-peak",   "demand_mult": 1.3,  "categories": ["grocery_staple", "fresh", "seasonal"], "regions": ["ALL"]},
    246: {"name": "Onam",            "demand_mult": 1.5,  "categories": ["grocery_staple", "fresh", "seasonal"], "regions": ["ALL"]},
    # Dussehra (~Oct 7)
    280: {"name": "Dussehra",        "demand_mult": 1.25, "categories": ["grocery_staple", "seasonal", "packaged"], "regions": ["ALL"]},
    281: {"name": "Dussehra peak",   "demand_mult": 1.35, "categories": ["grocery_staple", "seasonal", "packaged"], "regions": ["ALL"]},
    # Dhanteras + Diwali (~Oct 26 - Nov 1)
    299: {"name": "Dhanteras",       "demand_mult": 1.6,  "categories": ["seasonal", "household", "fmcg"],       "regions": ["ALL"]},
    301: {"name": "Diwali pre-peak", "demand_mult": 1.9,  "categories": ["grocery_staple", "seasonal", "fmcg", "packaged"], "regions": ["ALL"]},
    303: {"name": "Diwali",          "demand_mult": 2.4,  "categories": ["grocery_staple", "seasonal", "fmcg"],  "regions": ["ALL"]},
    304: {"name": "Diwali day+1",    "demand_mult": 1.6,  "categories": ["seasonal", "fresh"],                   "regions": ["ALL"]},
    305: {"name": "Bhai Dooj",       "demand_mult": 1.4,  "categories": ["seasonal", "grocery_staple"],          "regions": ["ALL"]},
    307: {"name": "Post-Diwali trough", "demand_mult": 0.75, "categories": ["seasonal", "grocery_staple"],       "regions": ["ALL"]},
    308: {"name": "Post-Diwali trough", "demand_mult": 0.78, "categories": ["seasonal", "grocery_staple"],       "regions": ["ALL"]},
    # Chhath (~Nov 6-11)
    310: {"name": "Chhath pre-peak", "demand_mult": 1.5,  "categories": ["grocery_staple", "fresh", "seasonal"], "regions": ["Ranchi", "Hazaribagh", "Dhanbad", "Jamshedpur"]},
    312: {"name": "Chhath peak",     "demand_mult": 1.9,  "categories": ["grocery_staple", "fresh", "seasonal"], "regions": ["Ranchi", "Hazaribagh", "Dhanbad", "Jamshedpur"]},
    313: {"name": "Chhath day+1",    "demand_mult": 1.3,  "categories": ["fresh", "grocery_staple"],             "regions": ["Ranchi", "Hazaribagh", "Dhanbad", "Jamshedpur"]},
    # Christmas / New Year
    359: {"name": "Christmas week",  "demand_mult": 1.25, "categories": ["seasonal", "packaged", "personal_care"], "regions": ["ALL"]},
    360: {"name": "Christmas day",   "demand_mult": 1.3,  "categories": ["seasonal", "fresh"],                   "regions": ["ALL"]},
    364: {"name": "New Year Eve",    "demand_mult": 1.4,  "categories": ["packaged", "seasonal", "fmcg"],        "regions": ["ALL"]},
    365: {"name": "New Year Day",    "demand_mult": 1.2,  "categories": ["fresh", "packaged"],                   "regions": ["ALL"]},
}

MONSOON_DAY_OF_YEAR_RANGE: Tuple[int, int] = (152, 273)

EPISODE_START_DAY_OF_YEAR: int = 274


def festival_for_episode_day(day_of_episode: int, start_day_of_year: int = EPISODE_START_DAY_OF_YEAR) -> Dict | None:
    day_of_year = ((start_day_of_year + day_of_episode - 1) % 365) + 1
    return ANNUAL_FESTIVAL_CALENDAR.get(day_of_year)


def is_monsoon_day(day_of_episode: int, start_day_of_year: int = EPISODE_START_DAY_OF_YEAR) -> bool:
    day_of_year = ((start_day_of_year + day_of_episode - 1) % 365) + 1
    return MONSOON_DAY_OF_YEAR_RANGE[0] <= day_of_year <= MONSOON_DAY_OF_YEAR_RANGE[1]
