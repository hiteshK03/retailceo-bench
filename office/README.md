# Retail CEO Pixel Office

A Claude-Office-inspired live dashboard for **RetailCEO-Bench** runs. A single-process
FastAPI backend (`office_api/`) drives a live `RetailCEOEnv` episode with a scripted,
pure-Python policy and streams UI events to a React 19 + PixiJS 8 SPA (`office/frontend`).

Everything here is **CPU-only and key-free** — no frontier API, no trained checkpoint.

## Run locally

Backend (serves the API and, if `office/frontend/dist` exists, the built SPA):

```bash
cd /home/hkandala/retailceo-bench
python3 -m uvicorn office_api.app:app --host 0.0.0.0 --port 7860 \
  --ws-ping-interval 300 --ws-ping-timeout 300
```

Open `http://localhost:7860`.

Frontend dev server (optional, hot reload; proxies `/api` + WS to port 7860):

```bash
cd office/frontend
npm install
npm run dev          # http://localhost:5173
```

## Build the bundle

```bash
cd office/frontend
npm install
npm run build        # regenerates office/frontend/dist (committed)
```

## API

- `GET  /api/health` — backend health.
- `POST /api/runs` — create a run config (`{ seed, policy, difficulty, weeks }`).
- `GET  /api/runs/{run_id}` — current run state + recent events.
- `WS   /api/runs/{run_id}/stream` — streams `run_started`, `week_started`,
  `agent_thinking`, `agent_called`, `week_completed`, `run_completed`, `run_failed`.

## Policies (scripted only)

`heuristic`, `oracle`, `all_approve`, `random` — all from `eval/policies.py`, no credentials.

## Notes

- Episodes are **12 weeks** by default (configurable 1–52) with an `easy | medium | hard`
  difficulty selector.
- The bench grader removed the SimMart "rogue proposal" governance mechanic, so there is
  no rogue ground truth. All rogue-only UI (badges, red markers) has been removed.
- RetailCEO-Bench ships no OpenEnv server app, so nothing is mounted under an env sub-path.
