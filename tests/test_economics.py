"""Economics constants and helper tests."""

from retailceo import economics as E


class TestConstants:
    def test_store_count(self):
        assert E.TOTAL_STARTING_STORES == 100

    def test_city_count(self):
        assert len(E.STARTING_CITIES) == 8

    def test_stores_per_city_sum(self):
        assert sum(E.STORES_PER_CITY.values()) == E.TOTAL_STARTING_STORES

    def test_sku_count(self):
        assert len(E.SKU_CATALOGUE) == 8

    def test_revenue_share_sums_to_one(self):
        total = sum(E.CATEGORY_REVENUE_SHARE.values())
        assert abs(total - 1.0) < 0.01

    def test_all_skus_have_required_fields(self):
        for sku_id, sku in E.SKU_CATALOGUE.items():
            assert "category" in sku
            assert "price_inr" in sku
            assert "cost_inr" in sku
            assert sku["price_inr"] > sku["cost_inr"], f"{sku_id} has no margin"

    def test_difficulty_maps_complete(self):
        for diff in ("easy", "medium", "hard"):
            assert diff in E.DIFFICULTY_DRIFT_MAP
            assert diff in E.DIFFICULTY_COGS_FACTOR
            assert diff in E.DIFFICULTY_GROWTH_LEVER_MULT
            assert diff in E.DIFFICULTY_DRIFT_JITTER

    def test_reward_weights_present(self):
        w = E.REWARD_WEIGHTS
        assert "weekly_kpi_delta" in w
        assert "quarterly_pnl" in w
        assert "cash_floor" in w


class TestSalaryCycleMultiplier:
    def test_payday_boost(self):
        assert E.salary_cycle_multiplier(1) > 1.0

    def test_mid_month_dip(self):
        assert E.salary_cycle_multiplier(17) < 1.0

    def test_range(self):
        for d in range(1, 31):
            m = E.salary_cycle_multiplier(d)
            assert 0.5 <= m <= 2.0, f"Day {d}: multiplier {m} out of range"


class TestFestivalCalendar:
    def test_diwali_exists(self):
        found = False
        for day, fest in E.FESTIVAL_CALENDAR.items():
            if fest["name"] == "Diwali":
                found = True
                assert fest["demand_mult"] > 1.0
        assert found, "Diwali should be in festival calendar"

    def test_festival_for_day(self):
        assert E.festival_for_day(62) is not None
        assert E.festival_for_day(1) is None

    def test_festival_demand_mults_positive(self):
        for day, fest in E.FESTIVAL_CALENDAR.items():
            assert fest["demand_mult"] > 0


class TestHelpers:
    def test_starting_sku_ids(self):
        ids = E.starting_sku_ids()
        assert len(ids) == 8
        assert all(isinstance(s, str) for s in ids)

    def test_skus_in_category(self):
        grocery = E.skus_in_category("grocery_staple")
        assert len(grocery) >= 1
        for sid in grocery:
            assert E.SKU_CATALOGUE[sid]["category"] == "grocery_staple"

    def test_baseline_units_populated(self):
        for cat in E.CATEGORY_REVENUE_SHARE:
            assert cat in E.CATEGORY_BASELINE_UNITS_PER_STORE_PER_DAY
            assert E.CATEGORY_BASELINE_UNITS_PER_STORE_PER_DAY[cat] > 0
