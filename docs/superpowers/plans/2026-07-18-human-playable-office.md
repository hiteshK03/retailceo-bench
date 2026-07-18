# Human-Playable Retail CEO Office Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a human play a RetailCEO episode through the Office UI — clicking approve/reject/modify/request_info each week — then record the playthrough to disk so many players form a human baseline comparable to the model leaderboard.

**Architecture:** A new bidirectional-WebSocket interactive runner (`office_api/interactive.py`) holds the env between weeks and awaits the human's decisions via an `asyncio.Queue`, selected by `mode="human"` on `RunConfig`. It reuses the existing event shapes and trace serializers, writes an eval-format recording on completion, and a `human-baseline` CLI aggregates recordings using the existing bootstrap stats.

**Tech Stack:** Python 3.10+, FastAPI, pydantic v2, `asyncio`; React 19 + TypeScript + PixiJS (existing office frontend); pytest.

## Global Constraints

- Python >= 3.10; core package depends only on `pydantic` (keep it that way).
- Must run key-free on the free CPU Space (no new required deps for the server path; `fastapi`/`uvicorn`/`websockets` already in `requirements.txt`).
- Recordings are local JSON only under `results/human/` — no DB, no auth, no email, no live leaderboard endpoint.
- Recording format mirrors the eval `trace` JSON (`{meta, trace, summary}`) so `eval.visualize` and aggregation work unchanged.
- Missing per-proposal decisions default to `request_info` (matches `retailceo.prompts.parse_response`); unknown proposal ids are dropped.
- Do NOT alter the existing scripted stream path (`mode="auto"` default, `stream_run`, `/api/runs/{id}/stream`).
- No `Math.random()`/`Date.now()` concerns here — the FastAPI server may use `time.time()` freely; the sim clock rules do not apply to the server.

---

### Task 1: Add `mode` + `player_handle` to RunConfig and a human-decision schema

**Files:**
- Modify: `office_api/schemas.py`
- Test: `tests/test_office_api.py`

**Interfaces:**
- Produces: `RunConfig.mode: Literal["auto","human"]` (default `"auto"`), `RunConfig.player_handle: Optional[str]`; new `HumanWeekDecisions` model with `week: int`, `decisions: List[Dict[str,Any]]`, `journal: str = ""`, `played_at: Optional[str] = None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_office_api.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_office_api.py -k "mode or human_week" -v`
Expected: FAIL (`mode` attribute missing / `HumanWeekDecisions` import error).

- [ ] **Step 3: Implement the schema changes**

In `office_api/schemas.py`, add to `RunConfig` (after `weeks`):

```python
    mode: Literal["auto", "human"] = "auto"
    player_handle: Optional[str] = Field(default=None, max_length=64)
```

Add a new model at the end of the file:

```python
class HumanWeekDecisions(BaseModel):
    """One week's decisions submitted by a human player over the socket."""

    week: int = Field(..., ge=1)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    journal: str = Field(default="")
    played_at: Optional[str] = Field(default=None, description="Client ISO8601")
```

(`Literal`, `Optional`, `List`, `Dict`, `Any`, `Field` are already imported.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_office_api.py -k "mode or human_week" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add office_api/schemas.py tests/test_office_api.py
git commit -m "Add human mode + decision schema to Office RunConfig"
```

---

### Task 2: Interactive runner — core turn-taking with reward parity

**Files:**
- Create: `office_api/interactive.py`
- Test: `tests/test_interactive.py`

**Interfaces:**
- Consumes: `RetailCEOEnv`, `BenchmarkConfig`, `CEOAction`, `ProposalDecision` from `retailceo`; `RunConfig` from `office_api.schemas`; `serialize_inbox`, `serialize_week`, `summarize_run` from `office_api.trace`.
- Produces:
  - `build_human_action(inbox, raw_decisions, journal="") -> CEOAction` — assembles a `CEOAction`; proposals absent from `raw_decisions` default to `request_info`; unknown ids dropped; invalid verdicts → `request_info`.
  - `async def play_interactive(run_id, config, recv_decisions, emit) -> dict` where `recv_decisions() -> Awaitable[HumanWeekDecisions-like dict]` supplies the next week's decisions and `emit(event: dict)` is an async callback for outbound events. Returns the final `run_completed` payload (also emitted).

**Note on testability:** `play_interactive` takes `recv_decisions`/`emit` callables so it can be driven in-process (no real socket). Task 5 wires it to the WebSocket.

- [ ] **Step 1: Write the failing test (parity)**

Create `tests/test_interactive.py`:

```python
import asyncio
import pytest

from office_api.schemas import RunConfig
from office_api import interactive
from retailceo.environment import RetailCEOEnv
from retailceo.models import BenchmarkConfig, CEOAction, ProposalDecision


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
    from retailceo.models import Proposal
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
    async def emit(ev): events.append(ev)

    # Scripted "human": approve every proposal in the week_started inbox.
    state = {"week_started": None}
    async def recv():
        ev = state["week_started"]
        return {"week": ev["payload"]["week"],
                "decisions": [{"proposal_id": p["proposal_id"], "verdict": "approve"}
                              for p in ev["payload"]["inbox"]]}

    # emit that also captures the latest week_started for recv() to answer
    async def emit_capture(ev):
        if ev["type"] == "week_started":
            state["week_started"] = ev
        events.append(ev)

    async def run():
        return await interactive.play_interactive("t1", cfg, recv, emit_capture)

    result = asyncio.run(run())
    rewards = [e["payload"]["reward"] for e in events if e["type"] == "week_completed"]
    assert rewards == pytest.approx(reference, rel=1e-12)
    assert result["summary"]["total_reward"] == pytest.approx(sum(reference), rel=1e-12)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_interactive.py -v`
Expected: FAIL (`office_api.interactive` does not exist).

- [ ] **Step 3: Implement `office_api/interactive.py`**

```python
"""Interactive (human-driven) Retail CEO episode runner.

Turn-taking over a bidirectional channel: emit `week_started`, await the
human's decisions, step the env, emit `week_completed`; repeat; then write a
recording and emit `run_completed`. Decoupled from the transport via the
`recv_decisions` / `emit` callables so it is unit-testable in-process.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict, List

from retailceo.environment import RetailCEOEnv
from retailceo.models import BenchmarkConfig, CEOAction, ProposalDecision

from .schemas import RunConfig
from .trace import serialize_inbox, serialize_week, summarize_run

_VALID_VERDICTS = {"approve", "reject", "modify", "request_info"}


def _event(event_type: str, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": event_type, "run_id": run_id, "ts": time.time(), "payload": payload}


def build_human_action(inbox, raw_decisions, journal: str = "") -> CEOAction:
    """Assemble a CEOAction from a human's raw decision dicts.

    Missing proposals default to request_info (a ledger no-op, matching
    prompts.parse_response); unknown ids are dropped; invalid verdicts →
    request_info.
    """
    by_id = {p.proposal_id for p in inbox}
    seen = set()
    decisions: List[ProposalDecision] = []
    for d in raw_decisions or []:
        pid = d.get("proposal_id")
        if pid is None or pid not in by_id or pid in seen:
            continue
        verdict = d.get("verdict", "request_info")
        if verdict not in _VALID_VERDICTS:
            verdict = "request_info"
        kwargs: Dict[str, Any] = {"proposal_id": pid, "verdict": verdict}
        mp = d.get("modified_params")
        if isinstance(mp, dict):
            kwargs["modified_params"] = mp
        if isinstance(d.get("reasoning"), str):
            kwargs["reasoning"] = d["reasoning"]
        decisions.append(ProposalDecision(**kwargs))
        seen.add(pid)
    for p in inbox:
        if p.proposal_id not in seen:
            decisions.append(ProposalDecision(proposal_id=p.proposal_id, verdict="request_info"))
    return CEOAction(action_type="decide", decisions=decisions, journal_entry=journal or "")


async def play_interactive(
    run_id: str,
    config: RunConfig,
    recv_decisions: Callable[[], Awaitable[Dict[str, Any]]],
    emit: Callable[[Dict[str, Any]], Awaitable[None]],
) -> Dict[str, Any]:
    started_at = time.time()
    bench = BenchmarkConfig(weeks_per_quarter=config.weeks,
                            difficulty=config.difficulty, seed=config.seed)
    env = RetailCEOEnv(bench)
    obs = env.reset(seed=config.seed)

    weekly_rewards: List[float] = []
    stockouts: List[float] = []
    nps_values: List[float] = []
    weeks: List[Dict[str, Any]] = []
    decision_wall: List[float] = []
    min_cash = env.state.company.cash_inr

    await emit(_event("run_started", run_id, {
        "config": config.model_dump(),
        "policy_name": "human",
        "max_weeks": env.MAX_WEEKS,
        "difficulty": config.difficulty,
        "initial_kpi": obs.kpi_snapshot.model_dump() if obs.kpi_snapshot else {},
        "initial_pnl": obs.pnl_snapshot.model_dump() if getattr(obs, "pnl_snapshot", None) else {},
    }))

    for week in range(1, env.MAX_WEEKS + 1):
        inbox_snapshot = serialize_inbox(obs.inbox)
        active = [c.crisis_id for c in obs.active_crises]
        await emit(_event("week_started", run_id, {
            "week": week, "inbox": inbox_snapshot, "active_crises": active,
            "kpi": obs.kpi_snapshot.model_dump() if obs.kpi_snapshot else {},
            "pnl_qtd": obs.pnl_snapshot.model_dump() if getattr(obs, "pnl_snapshot", None) else {},
        }))

        wait_start = time.time()
        msg = await recv_decisions()
        if int(msg.get("week", -1)) != week:
            raise ValueError(f"decision week {msg.get('week')} != expected {week}")
        decision_wall.append(time.time() - wait_start)

        action = build_human_action(obs.inbox, msg.get("decisions", []), msg.get("journal", ""))
        step_obs = env.step(action)
        reward = step_obs.reward or 0.0
        weekly_rewards.append(reward)
        if step_obs.kpi_snapshot:
            stockouts.append(step_obs.kpi_snapshot.stockout_rate_pct)
            nps_values.append(step_obs.kpi_snapshot.nps)
        min_cash = min(min_cash, env.state.company.cash_inr)

        payload = serialize_week(week=week, obs=obs, step_obs=step_obs, action=action,
                                 inbox_snapshot=inbox_snapshot, active_crises=active)
        payload["decision_wall_s"] = decision_wall[-1]
        weeks.append(payload)
        await emit(_event("week_completed", run_id, payload))

        obs = step_obs
        if obs.done:
            break

    summary = summarize_run(env=env, policy_name="human", seed=config.seed,
                            difficulty=config.difficulty, started_at=started_at,
                            weekly_rewards=weekly_rewards, stockouts=stockouts,
                            nps_values=nps_values, min_cash_inr=min_cash)
    summary["weeks"] = weeks
    await emit(_event("run_completed", run_id, summary))
    return summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_interactive.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add office_api/interactive.py tests/test_interactive.py
git commit -m "Add interactive human runner with reward parity"
```

---

### Task 3: Desync guard test

**Files:**
- Test: `tests/test_interactive.py`

**Interfaces:**
- Consumes: `interactive.play_interactive` from Task 2.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_interactive.py`:

```python
def test_play_interactive_rejects_wrong_week():
    cfg = RunConfig(mode="human", seed=44, weeks=12, difficulty="medium")
    async def emit(ev): pass
    async def recv():
        return {"week": 99, "decisions": []}  # wrong week
    with pytest.raises(ValueError, match="decision week"):
        asyncio.run(interactive.play_interactive("t2", cfg, recv, emit))
```

- [ ] **Step 2: Run test to verify it passes (guard already implemented in Task 2)**

Run: `python3 -m pytest tests/test_interactive.py::test_play_interactive_rejects_wrong_week -v`
Expected: PASS (the `int(msg.get("week")) != week` check raises).

- [ ] **Step 3: Commit**

```bash
git add tests/test_interactive.py
git commit -m "Test interactive week-desync guard"
```

---

### Task 4: Recording writer + round-trip

**Files:**
- Modify: `office_api/interactive.py`
- Create: `results/human/.gitkeep`
- Modify: `.gitignore`
- Test: `tests/test_interactive.py`

**Interfaces:**
- Produces: `write_recording(config, summary, results_dir="results/human") -> str` (returns path). `play_interactive` calls it before the final `run_completed` and adds `recording_path` to the emitted payload.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_interactive.py`:

```python
def test_write_recording_round_trips(tmp_path):
    from eval.visualize import load_trace
    cfg = RunConfig(mode="human", seed=44, weeks=4, difficulty="easy", player_handle="bob")
    summary = {"policy": "human", "seed": 44, "difficulty": "easy",
               "summary": {"total_reward": 1.0, "weekly_rewards": [0.5, 0.5],
                           "ebitda_margin_pct": 3.0, "final_cash_inr": 2e8,
                           "min_cash_inr": 1e8, "avg_stockout_pct": 2.0, "avg_nps": 35.0},
               "weeks": [{"week": 1, "reward": 0.5, "kpi": {}, "pnl_qtd": {}, "active_crises": []},
                         {"week": 2, "reward": 0.5, "kpi": {}, "pnl_qtd": {}, "active_crises": []}]}
    path = interactive.write_recording(cfg, summary, results_dir=str(tmp_path))
    payload = load_trace(path)   # validates {meta, trace}
    assert payload["meta"]["mode"] == "human"
    assert payload["meta"]["player_handle"] == "bob"
    assert payload["meta"]["difficulty"] == "easy"
    assert len(payload["trace"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_interactive.py::test_write_recording_round_trips -v`
Expected: FAIL (`write_recording` not defined).

- [ ] **Step 3: Implement `write_recording` and wire it in**

Add to `office_api/interactive.py` (imports `json`, `os`, `uuid` at top):

```python
import json
import os
import uuid


def write_recording(config: RunConfig, summary: Dict[str, Any],
                    results_dir: str = "results/human") -> str:
    os.makedirs(results_dir, exist_ok=True)
    handle = (config.player_handle or "anonymous").strip() or "anonymous"
    safe = "".join(c for c in handle if c.isalnum() or c in "-_")[:32] or "anon"
    short = uuid.uuid4().hex[:8]
    fname = f"{config.difficulty}_seed{config.seed}_{safe}_{short}.json"
    path = os.path.join(results_dir, fname)
    s = summary.get("summary", {})
    payload = {
        "meta": {
            "policy": "human", "mode": "human", "player_handle": handle,
            "seed": config.seed, "difficulty": config.difficulty,
            "played_at": summary.get("played_at") or _iso_now(),
            "total_reward": s.get("total_reward"),
            "final_cash_inr": s.get("final_cash_inr"),
            "ebitda_margin_pct": s.get("ebitda_margin_pct"),
            "avg_stockout_pct": s.get("avg_stockout_pct"),
            "avg_nps": s.get("avg_nps"),
        },
        "trace": summary.get("weeks", []),
        "summary": s,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

Then in `play_interactive`, replace the final block:

```python
    summary["weeks"] = weeks
    summary["played_at"] = _iso_now()
    recording_path = write_recording(config, summary)
    summary["recording_path"] = recording_path
    await emit(_event("run_completed", run_id, summary))
    return summary
```

- [ ] **Step 4: Add gitignore + gitkeep**

Create `results/human/.gitkeep` (empty). Append to `.gitignore` after the existing `results/archive_pre_reward_fix/` line:

```
results/human/
!results/human/.gitkeep
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_interactive.py::test_write_recording_round_trips -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add office_api/interactive.py tests/test_interactive.py .gitignore results/human/.gitkeep
git commit -m "Record human playthroughs to results/human in trace format"
```

---

### Task 5: Wire the WebSocket route

**Files:**
- Modify: `office_api/app.py`
- Test: `tests/test_office_api.py`

**Interfaces:**
- Consumes: `play_interactive` (Task 2); `HumanWeekDecisions`/`RunConfig` (Task 1).
- Produces: `WS /api/human/{run_id}/play`. The socket first accepts, then bridges: `emit = websocket.send_json`; `recv_decisions = lambda: websocket.receive_json()`. On `ValueError`/exception, sends a `run_failed` event and closes.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_office_api.py` (uses FastAPI's `TestClient` WebSocket support, already available via starlette):

```python
def test_human_play_websocket_full_episode():
    from fastapi.testclient import TestClient
    from office_api.app import app, RUNS
    from office_api.schemas import RunConfig

    client = TestClient(app)
    # create a human run
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_office_api.py::test_human_play_websocket_full_episode -v`
Expected: FAIL (404 / route missing).

- [ ] **Step 3: Implement the route**

In `office_api/app.py`, add after the existing `stream_run_socket` route (import `play_interactive` at top: `from .interactive import play_interactive`):

```python
@app.websocket("/api/human/{run_id}/play")
async def human_play_socket(websocket: WebSocket, run_id: str) -> None:
    record = RUNS.get(run_id)
    if record is None or record.config.mode != "human":
        await websocket.close(code=4404)
        return
    await websocket.accept()

    async def emit(event):
        record.append(event)
        await websocket.send_json(event)

    async def recv_decisions():
        return await websocket.receive_json()

    try:
        await play_interactive(run_id, record.config, recv_decisions, emit)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        event = {"type": "run_failed", "run_id": run_id,
                 "payload": {"error": type(exc).__name__, "message": str(exc)}}
        record.append(event)
        try:
            await websocket.send_json(event)
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_office_api.py::test_human_play_websocket_full_episode -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add office_api/app.py tests/test_office_api.py
git commit -m "Add /api/human/{run_id}/play WebSocket route"
```

---

### Task 6: Human-baseline aggregation + CLI

**Files:**
- Create: `eval/human_baseline.py`
- Modify: `eval/cli.py`
- Test: `tests/test_human_baseline.py`

**Interfaces:**
- Consumes: `eval.stats.bootstrap_ci_mean`.
- Produces: `aggregate(results_dir="results/human") -> Dict[str, Any]` grouping recordings by difficulty with mean/stderr/CI and player count; `write_baseline(agg, out="results/human_baseline.json")`. CLI: `python -m eval.cli human-baseline [--dir results/human] [--out results/human_baseline.json]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_human_baseline.py`:

```python
import json
from eval import human_baseline


def _rec(tmp_path, diff, seed, reward, handle="p"):
    p = tmp_path / f"{diff}_seed{seed}_{handle}_{seed}.json"
    p.write_text(json.dumps({
        "meta": {"mode": "human", "player_handle": handle, "seed": seed,
                 "difficulty": diff, "total_reward": reward},
        "trace": [], "summary": {"total_reward": reward},
    }))
    return p


def test_aggregate_groups_by_difficulty(tmp_path):
    _rec(tmp_path, "medium", 42, 1.0)
    _rec(tmp_path, "medium", 43, 2.0)
    _rec(tmp_path, "hard", 42, 0.0)
    agg = human_baseline.aggregate(results_dir=str(tmp_path))
    assert agg["medium"]["n"] == 2
    assert abs(agg["medium"]["mean"] - 1.5) < 1e-9
    assert "ci_lo" in agg["medium"] and "ci_hi" in agg["medium"]
    assert agg["hard"]["n"] == 1


def test_aggregate_empty_dir(tmp_path):
    assert human_baseline.aggregate(results_dir=str(tmp_path)) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_human_baseline.py -v`
Expected: FAIL (`eval.human_baseline` missing).

- [ ] **Step 3: Implement `eval/human_baseline.py`**

```python
"""Aggregate human playthrough recordings into a difficulty-grouped baseline."""

from __future__ import annotations

import glob
import json
import os
import statistics
from typing import Any, Dict, List

from . import stats as _stats


def _load_rewards_by_difficulty(results_dir: str) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        meta = d.get("meta", {})
        diff = meta.get("difficulty")
        reward = meta.get("total_reward")
        if diff is None or reward is None:
            continue
        out.setdefault(diff, []).append(float(reward))
    return out


def aggregate(results_dir: str = "results/human") -> Dict[str, Any]:
    grouped = _load_rewards_by_difficulty(results_dir)
    agg: Dict[str, Any] = {}
    for diff, rewards in grouped.items():
        mean, lo, hi = _stats.bootstrap_ci_mean(rewards)
        sd = statistics.stdev(rewards) if len(rewards) > 1 else 0.0
        stderr = sd / (len(rewards) ** 0.5) if rewards else 0.0
        agg[diff] = {"n": len(rewards), "mean": mean, "stderr": stderr,
                     "ci_lo": lo, "ci_hi": hi}
    return agg


def write_baseline(agg: Dict[str, Any], out: str = "results/human_baseline.json") -> str:
    with open(out, "w") as f:
        json.dump(agg, f, indent=2)
    return out
```

- [ ] **Step 4: Wire the CLI subcommand**

In `eval/cli.py`: add handler after `cmd_plot`:

```python
def cmd_human_baseline(args) -> int:
    from .human_baseline import aggregate, write_baseline
    agg = aggregate(results_dir=args.dir)
    if not agg:
        print(f"[human-baseline] no recordings found in {args.dir}")
        return 0
    print(f"\n=== Human baseline ({args.dir}) ===")
    print(f"{'difficulty':<10} {'n':>4} {'mean':>9}  95% CI")
    print("-" * 44)
    for diff in ("easy", "medium", "hard"):
        if diff in agg:
            a = agg[diff]
            print(f"{diff:<10} {a['n']:>4} {a['mean']:+9.3f}  "
                  f"[{a['ci_lo']:+.3f}, {a['ci_hi']:+.3f}]")
    out = write_baseline(agg, out=args.out)
    print(f"\nWrote {out}")
    return 0
```

Register the subparser after the `plot` subparser:

```python
    hb = sub.add_parser("human-baseline", help="Aggregate results/human/*.json into a baseline")
    hb.add_argument("--dir", type=str, default="results/human")
    hb.add_argument("--out", type=str, default="results/human_baseline.json")
```

Add dispatch after the `plot` branch:

```python
    elif args.command == "human-baseline":
        return cmd_human_baseline(args)
```

- [ ] **Step 5: Run test + CLI smoke**

Run: `python3 -m pytest tests/test_human_baseline.py -v`
Expected: PASS.
Run: `python3 -m eval.cli human-baseline --dir results/human`
Expected: prints "no recordings found" (dir empty) and exit 0.

- [ ] **Step 6: Commit**

```bash
git add eval/human_baseline.py eval/cli.py tests/test_human_baseline.py
git commit -m "Add human-baseline aggregation + CLI subcommand"
```

---

### Task 7: Frontend — API layer + types for human play

**Files:**
- Modify: `office/frontend/src/lib/api.ts`
- Modify: `office/frontend/src/types.ts`

**Interfaces:**
- Produces: `openHumanPlay(runId, onEvent) -> WebSocket` (same shape as `openRunStream` but hits `/api/human/{id}/play`); `RunConfig.mode?: "auto"|"human"`, `RunConfig.player_handle?: string`; `sendDecisions(ws, week, decisions)` helper.

- [ ] **Step 1: Extend types**

In `office/frontend/src/types.ts`, extend `RunConfig`:

```typescript
export type RunConfig = {
  seed: number;
  policy: PolicyKind;
  difficulty: Difficulty;
  weeks: number;
  mode?: "auto" | "human";
  player_handle?: string;
};
```

- [ ] **Step 2: Add the human-play socket helper**

In `office/frontend/src/lib/api.ts`, append:

```typescript
export function openHumanPlay(runId: string, onEvent: (event: OfficeEvent) => void): WebSocket {
  const socket = new WebSocket(`${wsBase()}/api/human/${runId}/play`);
  socket.addEventListener("message", (message) => {
    onEvent(JSON.parse(message.data) as OfficeEvent);
  });
  return socket;
}

export function sendDecisions(
  socket: WebSocket,
  week: number,
  decisions: { proposal_id: string; verdict: string; modified_params?: Record<string, unknown> }[],
): void {
  socket.send(JSON.stringify({ week, decisions }));
}
```

- [ ] **Step 3: Typecheck**

Run: `cd office/frontend && npm run build` (or `npx tsc --noEmit` if available)
Expected: no type errors from these files.

- [ ] **Step 4: Commit**

```bash
git add office/frontend/src/lib/api.ts office/frontend/src/types.ts
git commit -m "Frontend: human-play socket helpers + config types"
```

---

### Task 8: Frontend — interactive ProposalPanel

**Files:**
- Modify: `office/frontend/src/components/ProposalPanel.tsx`
- Modify: `office/frontend/src/styles/app.css`

**Interfaces:**
- Consumes: `Proposal`, `ProposalDecision` from types.
- Produces: `ProposalPanel` gains optional props `interactive?: boolean`, `pendingVerdicts?: Record<string, {verdict: string; modified_params?: Record<string, unknown>}>`, `onSetVerdict?: (proposalId, verdict, modified_params?) => void`. When `interactive`, each card renders Approve/Reject/Request-info buttons + a Modify qty input for `po.place`/`po.bulk_deal`; otherwise the existing read-only rendering is preserved.

- [ ] **Step 1: Add interactive props + buttons**

Replace the `Props` type and `ProposalCard` in `ProposalPanel.tsx` to accept the interactive props. Read-only path (no `interactive`) stays byte-identical in output. Interactive path renders:

```tsx
// inside ProposalCard, when interactive:
<div className="verdict-actions">
  {(["approve", "reject", "request_info"] as const).map((v) => (
    <button
      key={v}
      className={`verdict-btn ${pending?.verdict === v ? "active" : ""}`}
      onClick={() => onSetVerdict!(proposal.proposal_id, v)}
    >
      {v === "request_info" ? "Info" : v[0].toUpperCase() + v.slice(1)}
    </button>
  ))}
  {(proposal.action === "po.place" || proposal.action === "po.bulk_deal") && (
    <label className="modify-qty">
      qty
      <input
        type="number"
        defaultValue={Number(proposal.params?.qty ?? 0)}
        onChange={(e) =>
          onSetVerdict!(proposal.proposal_id, "modify", { qty: Number(e.target.value) })
        }
      />
    </label>
  )}
</div>
```

- [ ] **Step 2: Add CSS**

Append to `office/frontend/src/styles/app.css`:

```css
.verdict-actions { display: flex; gap: 6px; margin-top: 8px; align-items: center; flex-wrap: wrap; }
.verdict-btn { font: inherit; padding: 4px 8px; cursor: pointer; border: 2px solid #333; background: #f5f5f5; }
.verdict-btn.active { background: #2d6; color: #062; border-color: #062; }
.modify-qty { display: flex; gap: 4px; align-items: center; font-size: 0.85em; }
.modify-qty input { width: 90px; }
```

- [ ] **Step 3: Typecheck / build**

Run: `cd office/frontend && npm run build`
Expected: compiles.

- [ ] **Step 4: Commit**

```bash
git add office/frontend/src/components/ProposalPanel.tsx office/frontend/src/styles/app.css
git commit -m "Frontend: interactive proposal verdict controls"
```

---

### Task 9: Frontend — pre-game screen, play loop, end screen in App.tsx

**Files:**
- Modify: `office/frontend/src/App.tsx`

**Interfaces:**
- Consumes: `openHumanPlay`, `sendDecisions` (Task 7); interactive `ProposalPanel` (Task 8); `createRun` (existing).

- [ ] **Step 1: Add a "Human Play" flow**

Add state: `mode` ("spectate" | "human"), `handle`, `pendingVerdicts`, `awaitingWeek` (the week the human must submit). On "Start Human Game": pick `seed = 42 + Math.floor(externalRandom()*10)` — since the browser CAN use `Math.random()` (only the sim/workflow context forbids it), use `Math.floor(Math.random()*10)+42`; show it. `createRun({mode:"human", player_handle: handle||undefined, difficulty, seed, weeks:12, policy:"heuristic"})`, then `openHumanPlay(run_id, onEvent)` and store the socket in `socketRef`.

Event handling additions:
- On `week_started`: set `awaitingWeek = payload.week`, load `payload.inbox` into `currentWeek`, clear `pendingVerdicts`.
- On `week_completed`: append to history, clear `awaitingWeek` (advance).
- On `run_completed`: show end screen with `payload.summary` + `recording_path`.

- [ ] **Step 2: Render interactive panel + submit button when `awaitingWeek` set**

```tsx
{mode === "human" && awaitingWeek !== null && (
  <>
    <ProposalPanel
      week={currentWeek}
      interactive
      pendingVerdicts={pendingVerdicts}
      onSetVerdict={(pid, verdict, mp) =>
        setPendingVerdicts((p) => ({ ...p, [pid]: { verdict, modified_params: mp } }))
      }
    />
    <button
      className="submit-week"
      disabled={!allDecided(currentWeek, pendingVerdicts)}
      onClick={() => {
        const decisions = (currentWeek?.inbox ?? []).map((p) => ({
          proposal_id: p.proposal_id,
          verdict: pendingVerdicts[p.proposal_id]?.verdict ?? "request_info",
          modified_params: pendingVerdicts[p.proposal_id]?.modified_params,
        }));
        sendDecisions(socketRef.current!, awaitingWeek!, decisions);
        setAwaitingWeek(null);
      }}
    >
      Submit Week {awaitingWeek}
    </button>
  </>
)}
```

where `allDecided(week, pending)` returns true when every `week.inbox` id has an entry in `pending` (helper defined in App.tsx).

- [ ] **Step 3: End screen**

On `run_completed`, render the player's `total_reward`, `ebitda_margin_pct`, `final_cash_inr`, `avg_stockout_pct`, `avg_nps`, and a static comparison line vs heuristic/oracle for the seed's difficulty. Ship the baseline comparison numbers as a small static object in App.tsx sourced from `results/baselines_full.json` per-difficulty averages (easy/medium/hard heuristic & oracle rewards) — a fixed lookup, no new endpoint.

- [ ] **Step 4: Build + manual browser verification**

Run: `cd office/frontend && npm run build`
Then run the server: `python3 -m uvicorn office_api.app:app --port 7860` and open `http://localhost:7860`.
Verify: pre-game (handle + difficulty, seed shown) → play all 12 weeks clicking verdicts + one modify → end screen shows score + comparison → a JSON appears in `results/human/`.

- [ ] **Step 5: Commit**

```bash
git add office/frontend/src/App.tsx
git commit -m "Frontend: human play flow (pre-game, turn loop, end screen)"
```

---

### Task 10: Rebuild frontend bundle + README

**Files:**
- Modify: `office/frontend/dist/**` (rebuilt bundle)
- Modify: `README.md`

- [ ] **Step 1: Rebuild the committed bundle**

Run: `cd office/frontend && npm run build`
(The office serves `office/frontend/dist` directly; the bundle is committed so the Space needs no Node build step.)

- [ ] **Step 2: Add a README "Human Play" section**

Add after the "Live Office Demo" section:

```markdown
## Human Play

The Office can be played by a human to establish a **human baseline**. Launch
the server and open it in a browser:

    python -m uvicorn office_api.app:app --host 0.0.0.0 --port 7860
    # open http://localhost:7860 → "Human Play"

Enter an optional handle and pick a difficulty; the seed is drawn from the
official eval set (42–51) and shown. Each week, click Approve / Reject / Info
or Modify a PO quantity for every proposal, then Submit. At the end you see
your reward, KPIs, and how you rank vs the heuristic and oracle on that seed.

Every completed playthrough is recorded to `results/human/*.json` (same format
as `eval.cli trace`). Aggregate a human baseline across all recordings:

    python -m eval.cli human-baseline

which prints a per-difficulty mean ± bootstrap CI and writes
`results/human_baseline.json`.
```

Update the Roadmap: move "Human baseline (3–5 players)" from **Next** to **Done (this release)** as "human-playable Office + baseline aggregation".

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest -q`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add office/frontend/dist README.md
git commit -m "Rebuild office bundle + document Human Play"
```

---

## Self-Review

- **Spec coverage:** turn-taking protocol (T2,T5) · mode flag (T1) · desync guard (T3) · recording format (T4) · all-4-verdicts + modify (T8) · pre-game/end screen (T9) · protocol-aligned seed (T9) · optional handle (T1,T9) · aggregation (T6) · README (T10) · gitignore/gitkeep (T4). All covered.
- **Placeholder scan:** no TBDs; every code step has concrete code.
- **Type consistency:** `build_human_action`, `play_interactive(run_id, config, recv_decisions, emit)`, `write_recording(config, summary, results_dir)`, `aggregate(results_dir)`, `openHumanPlay`, `sendDecisions` used consistently across tasks.
- **Frontend clock:** browser `Math.random()`/`Date` are allowed (the sim/workflow clock constraint does not apply to browser code) — noted in T9.
