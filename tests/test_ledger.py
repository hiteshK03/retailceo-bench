"""Ledger tests — daily tick arithmetic, proposal execution, inventory."""

import random

from retailceo import economics as E
from retailceo import ledger as LD
from retailceo.models import (
    CompanyLedger,
    Proposal,
    ProposalDecision,
)


def _fresh_ledger(seed=42):
    rng = random.Random(seed)
    return LD.create_initial_ledger(rng, difficulty="medium"), rng


class TestCreateInitialLedger:
    def test_starting_cash(self):
        ledger, _ = _fresh_ledger()
        assert ledger.cash_inr == E.STARTING_CASH_INR

    def test_store_count(self):
        ledger, _ = _fresh_ledger()
        assert len(ledger.stores) == E.TOTAL_STARTING_STORES

    def test_city_count(self):
        ledger, _ = _fresh_ledger()
        assert len(ledger.cities) == len(E.STARTING_CITIES)

    def test_sku_catalogue(self):
        ledger, _ = _fresh_ledger()
        assert set(ledger.sku_catalogue.keys()) == set(E.SKU_CATALOGUE.keys())

    def test_inventory_populated(self):
        ledger, _ = _fresh_ledger()
        for sku_id in E.SKU_CATALOGUE:
            assert sku_id in ledger.inventory
            assert ledger.inventory[sku_id]["qty"] > 0
            assert ledger.inventory[sku_id]["value_inr"] > 0

    def test_franchisees_created(self):
        ledger, _ = _fresh_ledger()
        assert len(ledger.franchisees) > 0

    def test_difficulty_cogs_factor(self):
        rng = random.Random(1)
        easy = LD.create_initial_ledger(rng, difficulty="easy")
        rng = random.Random(1)
        hard = LD.create_initial_ledger(rng, difficulty="hard")
        assert easy.cogs_factor < hard.cogs_factor


class TestDailyTick:
    def test_tick_returns_telemetry(self):
        ledger, rng = _fresh_ledger()
        demand = {cat: 100.0 for cat in E.CATEGORY_REVENUE_SHARE}
        tel = LD.tick_one_day(
            ledger=ledger,
            day_of_quarter=1,
            category_demand_units=demand,
            sla_hit_rate_pct=90.0,
            crisis_extra_opex_inr=0.0,
            rng=rng,
        )
        assert "revenue_inr" in tel
        assert "cogs_inr" in tel
        assert "opex_inr" in tel
        assert "stockout_rate_pct" in tel
        assert tel["revenue_inr"] >= 0
        assert tel["opex_inr"] > 0

    def test_cash_decreases_with_opex(self):
        ledger, rng = _fresh_ledger()
        cash_before = ledger.cash_inr
        demand = {cat: 0.0 for cat in E.CATEGORY_REVENUE_SHARE}
        LD.tick_one_day(
            ledger=ledger,
            day_of_quarter=1,
            category_demand_units=demand,
            sla_hit_rate_pct=90.0,
            crisis_extra_opex_inr=0.0,
            rng=rng,
        )
        assert ledger.cash_inr < cash_before, "Opex should reduce cash"

    def test_revenue_adds_cash(self):
        ledger, rng = _fresh_ledger()
        cash_before = ledger.cash_inr
        demand = {cat: 5000.0 for cat in E.CATEGORY_REVENUE_SHARE}
        LD.tick_one_day(
            ledger=ledger,
            day_of_quarter=1,
            category_demand_units=demand,
            sla_hit_rate_pct=90.0,
            crisis_extra_opex_inr=0.0,
            rng=rng,
        )
        # Revenue should at least partially offset opex
        assert ledger.cash_inr > cash_before - E.BASELINE_WEEKLY_OPEX_INR

    def test_pnl_accumulation(self):
        ledger, rng = _fresh_ledger()
        demand = {cat: 1000.0 for cat in E.CATEGORY_REVENUE_SHARE}
        LD.tick_one_day(
            ledger=ledger,
            day_of_quarter=1,
            category_demand_units=demand,
            sla_hit_rate_pct=90.0,
            crisis_extra_opex_inr=0.0,
            rng=rng,
        )
        assert ledger.pnl_qtd.revenue_qtd_inr > 0
        assert ledger.pnl_qtd.cogs_qtd_inr > 0
        assert ledger.pnl_qtd.opex_qtd_inr > 0


class TestSellDailyDemand:
    def test_no_demand_no_revenue(self):
        ledger, rng = _fresh_ledger()
        result = LD.sell_daily_demand(ledger, {}, rng)
        assert result["revenue_inr"] == 0.0
        assert result["cogs_inr"] == 0.0

    def test_demand_generates_revenue(self):
        ledger, rng = _fresh_ledger()
        demand = {"grocery_staple": 500.0, "fmcg": 200.0}
        result = LD.sell_daily_demand(ledger, demand, rng)
        assert result["revenue_inr"] > 0
        assert result["cogs_inr"] > 0
        assert result["revenue_inr"] > result["cogs_inr"]

    def test_stockout_when_no_inventory(self):
        ledger, rng = _fresh_ledger()
        for inv in ledger.inventory.values():
            inv["qty"] = 0.0
        demand = {"grocery_staple": 500.0}
        result = LD.sell_daily_demand(ledger, demand, rng)
        assert result["stockout_rate_pct"] > 0

    def test_inventory_decreases_after_sale(self):
        ledger, rng = _fresh_ledger()
        total_before = sum(inv["qty"] for inv in ledger.inventory.values())
        demand = {"grocery_staple": 500.0, "fresh": 300.0}
        LD.sell_daily_demand(ledger, demand, rng)
        total_after = sum(inv["qty"] for inv in ledger.inventory.values())
        assert total_after < total_before


class TestShrinkageAndSpoilage:
    def test_shrinkage_reduces_inventory(self):
        ledger, rng = _fresh_ledger()
        total_before = sum(inv["qty"] for inv in ledger.inventory.values())
        LD.apply_shrinkage_and_spoilage(ledger, rng)
        total_after = sum(inv["qty"] for inv in ledger.inventory.values())
        assert total_after <= total_before

    def test_returns_value_dict(self):
        ledger, rng = _fresh_ledger()
        result = LD.apply_shrinkage_and_spoilage(ledger, rng)
        assert "shrinkage_value_inr" in result
        assert result["shrinkage_value_inr"] >= 0


class TestProposalExecution:
    def _po_proposal(self, sku_id="wheat-flour-5kg", qty=10000):
        return Proposal(
            proposal_id="TEST-PO-01",
            dept="supply_chain",
            action="po.place",
            params={"sku_id": sku_id, "qty": qty, "lead_days": 2},
            cost_inr=qty * 150,
            urgency="high",
            reasoning="Restock",
            week_submitted=1,
        )

    def test_approve_po_adds_inventory(self):
        ledger, rng = _fresh_ledger()
        sku_id = list(ledger.sku_catalogue.keys())[0]
        qty_before = ledger.inventory[sku_id]["qty"]
        proposal = self._po_proposal(sku_id=sku_id, qty=5000)
        decision = ProposalDecision(
            proposal_id="TEST-PO-01", verdict="approve", reasoning="ok"
        )
        LD.execute_approved_proposals(ledger, [proposal], [decision], rng)
        assert ledger.inventory[sku_id]["qty"] > qty_before

    def test_reject_po_no_change(self):
        ledger, rng = _fresh_ledger()
        sku_id = list(ledger.sku_catalogue.keys())[0]
        qty_before = ledger.inventory[sku_id]["qty"]
        cash_before = ledger.cash_inr
        proposal = self._po_proposal(sku_id=sku_id, qty=5000)
        decision = ProposalDecision(
            proposal_id="TEST-PO-01", verdict="reject", reasoning="no"
        )
        LD.execute_approved_proposals(ledger, [proposal], [decision], rng)
        assert ledger.inventory[sku_id]["qty"] == qty_before
        assert ledger.cash_inr == cash_before

    def test_modify_po_uses_modified_qty(self):
        ledger, rng = _fresh_ledger()
        sku_id = list(ledger.sku_catalogue.keys())[0]
        qty_before = ledger.inventory[sku_id]["qty"]
        proposal = self._po_proposal(sku_id=sku_id, qty=10000)
        decision = ProposalDecision(
            proposal_id="TEST-PO-01",
            verdict="modify",
            modified_params={"qty": 3000},
            reasoning="reduce",
        )
        LD.execute_approved_proposals(ledger, [proposal], [decision], rng)
        added = ledger.inventory[sku_id]["qty"] - qty_before
        assert 2500 < added < 3500, f"Expected ~3000 added, got {added}"

    def test_request_info_no_change(self):
        ledger, rng = _fresh_ledger()
        cash_before = ledger.cash_inr
        proposal = self._po_proposal(qty=5000)
        decision = ProposalDecision(
            proposal_id="TEST-PO-01", verdict="request_info", reasoning="need more detail"
        )
        LD.execute_approved_proposals(ledger, [proposal], [decision], rng)
        assert ledger.cash_inr == cash_before

    def test_campaign_launch(self):
        ledger, rng = _fresh_ledger()
        proposal = Proposal(
            proposal_id="TEST-CAMP-01",
            dept="growth",
            action="campaign.launch",
            params={"channel": "local_media", "duration_weeks": 2, "spend_inr": 500000},
            cost_inr=500000,
            urgency="med",
            reasoning="Growth push",
            week_submitted=1,
        )
        decision = ProposalDecision(
            proposal_id="TEST-CAMP-01", verdict="approve", reasoning="go"
        )
        cash_before = ledger.cash_inr
        LD.execute_approved_proposals(ledger, [proposal], [decision], rng)
        assert ledger.cash_inr < cash_before

    def test_line_of_credit_draw(self):
        ledger, rng = _fresh_ledger()
        proposal = Proposal(
            proposal_id="TEST-LOC-01",
            dept="finance",
            action="line_of_credit.draw",
            params={"amount_inr": 5e7},
            cost_inr=0,
            urgency="high",
            reasoning="Liquidity",
            week_submitted=1,
        )
        decision = ProposalDecision(
            proposal_id="TEST-LOC-01", verdict="approve", reasoning="ok"
        )
        cash_before = ledger.cash_inr
        LD.execute_approved_proposals(ledger, [proposal], [decision], rng)
        assert ledger.cash_inr > cash_before


class TestSnapshotWeeklyKPIs:
    def test_snapshot_appended_to_history(self):
        ledger, _ = _fresh_ledger()
        history_len_before = len(ledger.kpi_history)
        LD.snapshot_weekly_kpis(
            ledger=ledger,
            weekly_revenue=5e7,
            weekly_cogs=4.35e7,
            weekly_stockout_rate_pct=5.0,
            weekly_shrinkage_pct=2.0,
            weekly_sla_hit_rate_pct=90.0,
            weekly_nps=35.0,
            weekly_basket_inr=450.0,
            weekly_footfall_per_store=500.0,
            weekly_repeat_purchase_pct=45.0,
        )
        assert len(ledger.kpi_history) == history_len_before + 1

    def test_snapshot_fields(self):
        ledger, _ = _fresh_ledger()
        snap = LD.snapshot_weekly_kpis(
            ledger=ledger,
            weekly_revenue=6e7,
            weekly_cogs=5e7,
            weekly_stockout_rate_pct=3.0,
            weekly_shrinkage_pct=1.5,
            weekly_sla_hit_rate_pct=92.0,
            weekly_nps=38.0,
            weekly_basket_inr=470.0,
            weekly_footfall_per_store=520.0,
            weekly_repeat_purchase_pct=47.0,
        )
        assert snap.revenue_inr == 6e7
        assert snap.stockout_rate_pct == 3.0
        assert snap.nps == 38.0
