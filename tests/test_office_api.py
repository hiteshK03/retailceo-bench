"""Smoke tests for the bench-backed Retail CEO Office backend."""

import asyncio

import pytest

from office_api.policies import build_policy
from office_api.runner import stream_run
from office_api.schemas import RunConfig

SCRIPTED_POLICIES = ["heuristic", "oracle", "all_approve", "random"]


def _collect(config: RunConfig):
    async def go():
        return [ev async for ev in stream_run("test-run", config)]

    return asyncio.run(go())


def test_build_policy_scripted_only():
    for name in SCRIPTED_POLICIES:
        policy = build_policy(RunConfig(policy=name))
        assert policy.name == name


def test_build_policy_rejects_unknown():
    cfg = RunConfig(policy="heuristic")
    object.__setattr__(cfg, "policy", "frontier")  # bypass validation
    with pytest.raises(ValueError):
        build_policy(cfg)


def test_event_sequence_full_episode():
    weeks = 4
    events = _collect(RunConfig(seed=42, policy="heuristic", difficulty="medium", weeks=weeks))
    types = [e["type"] for e in events]

    assert types[0] == "run_started"
    assert types[-1] == "run_completed"
    assert types.count("week_started") == weeks
    assert types.count("agent_thinking") == weeks
    assert types.count("agent_called") == weeks
    assert types.count("week_completed") == weeks

    # Per-week ordering: started -> thinking -> called -> completed
    body = types[1:-1]
    assert body == ["week_started", "agent_thinking", "agent_called", "week_completed"] * weeks


def test_run_started_reports_max_weeks_and_difficulty():
    events = _collect(RunConfig(seed=1, policy="random", difficulty="hard", weeks=6))
    started = events[0]["payload"]
    assert started["max_weeks"] == 6
    assert started["difficulty"] == "hard"
    assert started["policy_name"] == "random"


def test_week_payload_shape_no_rogue():
    events = _collect(RunConfig(seed=7, policy="heuristic", difficulty="easy", weeks=3))
    week_events = [e for e in events if e["type"] == "week_completed"]
    assert [e["payload"]["week"] for e in week_events] == [1, 2, 3]

    payload = week_events[0]["payload"]
    for key in ("week", "inbox", "decisions", "journal", "reward", "kpi", "pnl_qtd", "cash_inr"):
        assert key in payload
    # Rogue mechanic was removed from the bench — no rogue keys should leak.
    assert "is_rogue" not in payload
    for proposal in payload["inbox"]:
        assert "is_rogue" not in proposal
        assert "rogue_meta" not in proposal
    for decision in payload["decisions"]:
        assert decision["verdict"] in ("approve", "reject", "modify", "request_info")


def test_run_completed_summary():
    events = _collect(RunConfig(seed=42, policy="all_approve", difficulty="medium", weeks=12))
    summary = events[-1]["payload"]
    assert summary["policy"] == "all_approve"
    assert summary["difficulty"] == "medium"
    assert len(summary["weeks"]) == 12
    assert "total_reward" in summary["summary"]
    assert "rogue_ground_truth" not in summary


def test_runconfig_defaults_to_auto_mode():
    from office_api.schemas import RunConfig
    cfg = RunConfig()
    assert cfg.mode == "auto"
    assert cfg.player_handle is None


def test_runconfig_accepts_human_mode_and_handle():
    from office_api.schemas import RunConfig
    cfg = RunConfig(mode="human", player_handle="alice", difficulty="hard", seed=44)
    assert cfg.mode == "human" and cfg.player_handle == "alice"


def test_human_week_decisions_model():
    from office_api.schemas import HumanWeekDecisions
    msg = HumanWeekDecisions(week=1, decisions=[{"proposal_id": "S-1", "verdict": "approve"}])
    assert msg.week == 1 and msg.decisions[0]["verdict"] == "approve"
    assert msg.journal == ""


def test_human_play_websocket_full_episode():
    from fastapi.testclient import TestClient
    from office_api.app import app

    client = TestClient(app)
    r = client.post("/api/runs", json={"mode": "human", "seed": 44,
                                       "difficulty": "easy", "weeks": 4})
    run_id = r.json()["run_id"]

    with client.websocket_connect(f"/api/human/{run_id}/play") as ws:
        completed = None
        while True:
            ev = ws.receive_json()
            if ev["type"] == "week_started":
                ws.send_json({"week": ev["payload"]["week"],
                              "decisions": [{"proposal_id": p["proposal_id"], "verdict": "approve"}
                                            for p in ev["payload"]["inbox"]]})
            elif ev["type"] == "run_completed":
                completed = ev
                break
            elif ev["type"] == "run_failed":
                raise AssertionError(ev["payload"])
        assert completed["payload"]["summary"]["total_reward"] is not None
        assert "recording_path" in completed["payload"]
