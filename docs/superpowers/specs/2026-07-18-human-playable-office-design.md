# Human-Playable Retail CEO Office — Design

**Date:** 2026-07-18
**Status:** Approved (brainstorming) → ready for implementation plan

## Goal

Turn the existing "Pixel CEO Office" (currently a one-way spectator demo of
scripted policies) into a **human-playable** benchmark: a person clicks through
each week's proposals — approve / reject / modify / request_info — and at the
end sees their reward, KPIs, and how they rank against the heuristic/oracle on
the same seed. Each completed playthrough is recorded to disk so that, across
many players, we can build a **human baseline** directly comparable to the
model leaderboard (roadmap item).

## Requirements (settled in brainstorming)

- **Persistence:** local JSON recording only (`results/human/`), same trace
  format as the eval `trace` command. No DB, no auth, no live leaderboard
  endpoint. Must keep working key-free on the free CPU Space.
- **Action fidelity:** all four verdicts (approve / reject / modify /
  request_info), including a `modify` affordance for PO quantity — so human
  decisions are directly comparable to LLM/heuristic policies.
- **Run config:** protocol-aligned. Player picks difficulty; seed is drawn from
  the eval set (42–51) and shown. This makes recordings slot into the official
  per-difficulty protocol. (No leakage concern — humans are not being trained.)
- **Identity:** optional handle typed before start (else "anonymous"). No email,
  no accounts.

## Non-goals (YAGNI)

- No accounts / auth / email.
- No database or live leaderboard service.
- No client-side simulation (would risk scoring divergence from the benchmark).
- No `budget_allocations` control (the field is inert / unscored).

## Architecture

### Turn-taking (approach A: bidirectional WebSocket + async decision queue)

A new interactive runner lives alongside the existing `stream_run`, selected by
a `mode` field on `RunConfig` (`"auto"` = existing scripted stream, default;
`"human"` = interactive). The existing scripted path is untouched.

New module `office_api/interactive.py` and a new route
`WS /api/human/{run_id}/play`. The socket is **bidirectional**. The runner
holds `env` + `obs` between messages and awaits an `asyncio.Queue` fed by
inbound WS messages.

Protocol per episode:

```
server → run_started      {config, policy_name:"human", max_weeks, initial_kpi, initial_pnl}
loop each week:
  server → week_started   {week, inbox, active_crises, kpi, pnl_qtd}
  client → decisions      {week, decisions:[{proposal_id, verdict, modified_params?}],
                           journal?, decision_wall_s?}
  server → week_completed {serialize_week(...) payload}   # emitted after env.step()
server → run_completed    {summarize_run(...) + weeks[] + recording_path}
(server → run_failed      {error, message}   on any exception)
```

**Desync guard:** the server validates each inbound `decisions` message targets
the expected `week` and covers the current inbox. Any proposal without a
decision defaults to `request_info` (matching `retailceo.prompts.parse_response`
fallback semantics), and unknown proposal ids are dropped. A message for the
wrong week is rejected with a `run_failed`-style error rather than stepping the
env, so a rushed/malformed client cannot desync the simulation.

### Reuse

The interactive runner reuses the existing serialization verbatim:
`serialize_inbox`, `serialize_week`, `summarize_run` (`office_api/trace.py`).
Emitted event shapes match the existing `week_started` / `week_completed` /
`run_completed` events, so the frontend's current event handlers work
unchanged. A human `CEOAction` is assembled from the inbound decisions using
the same `CEOAction` / `ProposalDecision` models the env already consumes.

## Data recording

On `run_completed`, the runner writes:

```
results/human/<difficulty>_seed<NN>_<handle-or-anon>_<shortid>.json
```

Format mirrors the eval trace JSON so existing tooling works with zero changes:

```json
{
  "meta": {
    "policy": "human",
    "mode": "human",
    "player_handle": "<handle or 'anonymous'>",
    "seed": 44,
    "difficulty": "medium",
    "played_at": "<client-supplied ISO8601>",
    "total_reward": 1.23,
    "final_cash_inr": ...,
    "ebitda_margin_pct": ...,
    "avg_stockout_pct": ...,
    "avg_nps": ...
  },
  "trace": [ { week, day, inbox_size, decisions, reward, kpi, active_crises,
               pnl_qtd, decision_wall_s }, ... ],
  "summary": { ...summarize_run summary... }
}
```

Notes:
- `decision_wall_s` is measured server-side with `time.time()` (the FastAPI
  server may call the clock freely). `played_at` is set server-side with
  `time.time()` at `run_completed`; a client-supplied ISO timestamp, if sent,
  is accepted as an override.
- `results/human/` is gitignored except a committed `.gitkeep`. Recordings are
  local artifacts, not committed.
- The `trace[]` entries are compatible with `eval.visualize.plot_trace` and the
  aggregation tool below.

## Frontend

Reuse the existing office shell (React 19 + PixiJS). Changes:

1. **Pre-game screen:** optional handle text field + difficulty picker (easy /
   medium / hard). Seed is auto-drawn client-side from 42–51 and displayed
   (so the player knows which protocol instance they got). A "Start" button
   opens the `/api/human/{run_id}/play` socket.
2. **Interactive `ProposalPanel`:** each proposal card gets Approve / Reject /
   Request-info buttons and a Modify affordance — an inline numeric editor for
   PO `qty` (the primary modify lever for `po.place` / `po.bulk_deal`). Verdict
   state is held per proposal; a "Submit week" button sends the batch and is
   disabled until every proposal has a verdict (or provides a "reject/request
   remaining" default). `manualReview` (already present) is repurposed to gate
   on human submission rather than a display timer.
3. **End screen:** shows the player's total reward, EBITDA %, final cash,
   avg stockout, avg NPS, and a comparison line vs the heuristic and oracle on
   the same seed + difficulty (these baseline numbers can be shipped as a static
   lookup generated from `results/baselines_full.json`, or fetched from a small
   read-only endpoint — implementation detail for the plan).

## Human baseline aggregation

New `eval/human_baseline.py` + a `human-baseline` CLI subcommand:

- Scans `results/human/*.json`, groups by difficulty.
- Prints mean ± stderr reward and a bootstrap 95% CI (reusing `eval/stats.py`),
  in the same shape as the leaderboard, plus per-player counts.
- Writes `results/human_baseline.json` as the aggregated artifact.

## Testing

- **Backend parity test** (`tests/test_interactive.py`): drive
  `interactive.py` in-process with a scripted "human" that feeds decisions via
  the queue (approve-all), asserting per-week reward parity with
  `run_one_episode` for a fixed seed — same guardrail as the OpenEnv parity
  test. Plus a test for the week-desync guard (wrong-week message rejected;
  missing proposals default to request_info).
- **Recording round-trip:** a completed interactive run writes a JSON that
  loads in `eval.visualize.load_trace` and in the aggregation tool.
- **Frontend:** not unit-tested (consistent with the existing office). Will be
  driven in a browser before completion — pre-game → play a full episode →
  end screen → recording written.

## README

New "Human Play" section: how to launch the office in human mode, the
protocol-aligned flow, where recordings land, and how to build the human
baseline (`human-baseline` subcommand). Update the roadmap: human baseline
moves from "next" to in-progress/available.

## Files touched

New:
- `office_api/interactive.py` — interactive runner (turn-taking, recording).
- `eval/human_baseline.py` — aggregation.
- `tests/test_interactive.py` — parity + guard tests.
- `results/human/.gitkeep`.
- Frontend: pre-game + end-screen components; interactive `ProposalPanel`.

Modified:
- `office_api/schemas.py` — add `mode` to `RunConfig`, human decision message
  schema, optional `player_handle`.
- `office_api/app.py` — new `/api/human/{run_id}/play` route.
- `eval/cli.py` — `human-baseline` subcommand.
- `.gitignore` — `results/human/` (keep `.gitkeep`).
- `README.md` — Human Play section + roadmap.
- Frontend `App.tsx`, `types.ts`, `lib/api.ts`, `styles/app.css`.
```
