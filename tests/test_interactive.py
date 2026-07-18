import asyncio
import pytest

from office_api.schemas import RunConfig
from office_api import interactive
from retailceo.environment import RetailCEOEnv
from retailceo.models import BenchmarkConfig, CEOAction, ProposalDecision, Proposal


def _core_approve_all_rewards(seed, weeks, difficulty):
    env = RetailCEOEnv(BenchmarkConfig(weeks_per_quarter=weeks, difficulty=difficulty))
    obs = env.reset(seed=seed)
    rewards = []
    while not obs.done:
        action = CEOAction(action_type="decide", decisions=[
            ProposalDecision(proposal_id=p.proposal_id, verdict="approve") for p in obs.inbox
        ])
        obs = env.step(action)
        if obs.reward is not None:
            rewards.append(obs.reward)
    return rewards


def test_build_human_action_defaults_missing_to_request_info():
    inbox = [Proposal(proposal_id="S-1", dept="supply_chain", action="po.place"),
             Proposal(proposal_id="S-2", dept="supply_chain", action="po.place")]
    action = interactive.build_human_action(inbox, [{"proposal_id": "S-1", "verdict": "approve"}])
    verdicts = {d.proposal_id: d.verdict for d in action.decisions}
    assert verdicts == {"S-1": "approve", "S-2": "request_info"}


def test_play_interactive_approve_all_matches_core():
    seed, weeks, diff = 44, 12, "medium"
    reference = _core_approve_all_rewards(seed, weeks, diff)
    cfg = RunConfig(mode="human", seed=seed, weeks=weeks, difficulty=diff, player_handle="t")

    events = []
    state = {"week_started": None}

    async def recv():
        ev = state["week_started"]
        return {"week": ev["payload"]["week"],
                "decisions": [{"proposal_id": p["proposal_id"], "verdict": "approve"}
                              for p in ev["payload"]["inbox"]]}

    async def emit_capture(ev):
        if ev["type"] == "week_started":
            state["week_started"] = ev
        events.append(ev)

    result = asyncio.run(interactive.play_interactive("t1", cfg, recv, emit_capture))
    rewards = [e["payload"]["reward"] for e in events if e["type"] == "week_completed"]
    assert rewards == pytest.approx(reference, rel=1e-12)
    assert result["summary"]["total_reward"] == pytest.approx(sum(reference), rel=1e-12)


def test_write_recording_round_trips(tmp_path):
    from eval.visualize import load_trace
    cfg = RunConfig(mode="human", seed=44, weeks=4, difficulty="easy", player_handle="bob")
    summary = {
        "policy": "human", "seed": 44, "difficulty": "easy",
        "summary": {"total_reward": 1.0, "weekly_rewards": [0.5, 0.5],
                    "ebitda_margin_pct": 3.0, "final_cash_inr": 2e8,
                    "min_cash_inr": 1e8, "avg_stockout_pct": 2.0, "avg_nps": 35.0},
        "weeks": [{"week": 1, "reward": 0.5, "kpi": {}, "pnl_qtd": {}, "active_crises": []},
                  {"week": 2, "reward": 0.5, "kpi": {}, "pnl_qtd": {}, "active_crises": []}],
    }
    path = interactive.write_recording(cfg, summary, results_dir=str(tmp_path))
    payload = load_trace(path)
    assert payload["meta"]["mode"] == "human"
    assert payload["meta"]["player_handle"] == "bob"
    assert payload["meta"]["difficulty"] == "easy"
    assert len(payload["trace"]) == 2


def test_play_interactive_rejects_wrong_week():
    cfg = RunConfig(mode="human", seed=44, weeks=12, difficulty="medium")

    async def emit(ev):
        pass

    async def recv():
        return {"week": 99, "decisions": []}

    with pytest.raises(ValueError, match="decision week"):
        asyncio.run(interactive.play_interactive("t2", cfg, recv, emit))
