# RetailCEO-Bench

[![CI](https://github.com/hiteshK03/retailceo-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/hiteshK03/retailceo-bench/actions/workflows/ci.yml)

<p align="center">
  <img src="assets/office.png" alt="Retail CEO Office — live simulation dashboard with top KPI bar (EBITDA, Revenue, Cash, Stock-out, NPS) above the pixel office" width="900">
</p>

<p align="center"><em>The live &quot;Pixel CEO Office&quot; dashboard — a scripted <code>RetailCEOEnv</code> episode streaming weekly KPIs, department proposals, and live CEO decisions.</em></p>

> **🏪 Live "Pixel CEO Office" demo (Hugging Face Docker Space).** This repo doubles as a
> CPU-only, key-free Hugging Face Space that streams a live `RetailCEOEnv` episode driven by a
> scripted policy into a React + PixiJS dashboard. The backend lives in
> [`office_api/`](./office_api/), the frontend in [`office/frontend/`](./office/frontend/)
> (prebuilt bundle committed under `office/frontend/dist`). Container entry point is the
> [`Dockerfile`](./Dockerfile). See [Live Office Demo](#live-office-demo) below.

**Can LLMs run a retail chain profitably?**

RetailCEO-Bench is an evaluation benchmark that tests how well large language models can operate as CEO of a simulated tier-2 Indian retail chain over a 12-week quarter (or multi-year horizon). The LLM receives weekly KPI reports, department proposals, crisis alerts, and competitor intelligence, then must make approval/rejection/modification decisions that keep the company profitable, solvent, and growing.

---

## Leaderboard (Full Protocol: 10 Seeds × 3 Difficulties)

| Policy | Easy | Medium | Hard | Avg |
|--------|------|--------|------|-----|
| Heuristic (19 rules) | +2.03 | +1.62 | +0.26 | +1.30 |
| **Claude Sonnet 4** | +1.63 | +1.16 | +0.34 | +1.04 |
| **Claude Opus 4** | +1.56 | +1.05 | +0.27 | +0.96 |
| All-Approve | +1.85 | +1.13 | -0.54 | +0.81 |
| Random | +0.31 | -0.29 | -1.41 | -0.46 |

> **Reward range:** theoretical [-4.5, +3.5]. Higher is better.
> Frontier models currently underperform the hand-crafted Heuristic baseline — closing this gap is the benchmark's core challenge.

<details>
<summary>Extended metrics (click to expand)</summary>

| Policy | Difficulty | Reward | EBITDA% | Stockout% | NPS | FCF (Cr) |
|--------|-----------|--------|---------|-----------|-----|----------|
| Heuristic | Easy | +2.03 | +10.37 | 1.8 | 34.4 | +37.4 |
| Heuristic | Medium | +1.62 | +5.82 | 0.9 | 34.1 | +36.1 |
| Heuristic | Hard | +0.26 | +0.99 | 1.2 | 32.7 | +27.6 |
| Sonnet 4 | Easy | +1.63 | +8.95 | 5.6 | 30.6 | +21.4 |
| Sonnet 4 | Medium | +1.16 | +4.55 | 4.5 | 30.8 | +19.8 |
| Sonnet 4 | Hard | +0.34 | +0.18 | 2.2 | 32.9 | +12.5 |
| Opus 4 | Easy | +1.56 | +8.72 | 9.0 | 28.6 | +22.7 |
| Opus 4 | Medium | +1.05 | +4.11 | 6.7 | 29.5 | +19.5 |
| Opus 4 | Hard | +0.27 | +0.15 | 2.7 | 32.3 | +17.1 |

</details>

---

## Glossary

New to business/finance terminology? Here's what the metrics in the leaderboard mean:

| Term | Full Form | What It Means |
|------|-----------|---------------|
| **EBITDA** | Earnings Before Interest, Taxes, Depreciation & Amortization | The company's operating profit — revenue minus the cost of goods and operating expenses. A positive EBITDA% means the business is making money from operations. |
| **EBITDA%** | EBITDA Margin | EBITDA as a percentage of revenue. +7% means the company keeps ₹7 of every ₹100 in revenue as operating profit. |
| **FCF** | Free Cash Flow | The net cash generated (or burned) during the episode. Starting cash was ₹20 Cr; if final cash is ₹41 Cr, FCF = +₹21 Cr. |
| **NPS** | Net Promoter Score | A customer satisfaction metric ranging from -100 to +100. Measures how likely customers are to recommend the store. Baseline is 35; below 25 is poor. |
| **Stockout%** | Stockout Rate | Percentage of customer demand that couldn't be fulfilled because inventory was empty. Target is <5%; above 8% means significant lost sales. |
| **COGS** | Cost of Goods Sold | The direct cost of purchasing the products that were sold (e.g., buying wheat flour from suppliers to sell in stores). |
| **OPEX** | Operating Expenses | Day-to-day running costs: staff salaries, rent, utilities, logistics — everything except the cost of goods themselves. |
| **P&L** | Profit and Loss Statement | A financial summary showing revenue, costs, and whether the company made or lost money. |
| **SLA** | Service Level Agreement | Here, the percentage of deliveries completed on time. Baseline is 90%. |
| **KPI** | Key Performance Indicator | A measurable metric used to track business health (revenue, margins, stockouts, NPS, etc.). |
| **PO** | Purchase Order | A formal order placed with suppliers to buy inventory. The CEO can modify PO quantities to balance cash vs. stockout risk. |
| **Cr** | Crore | Indian numbering unit = 10 million. ₹20 Cr = ₹200,000,000 (~$2.4M USD). |
| **SKU** | Stock Keeping Unit | A distinct product in inventory. The simulation has 8 SKUs (wheat flour, rice, oil, soap, detergent, milk, bread, batteries). |
| **Capex** | Capital Expenditure | Large one-time investments (new stores, equipment, technology) as opposed to ongoing operating expenses. |
| **Line of Credit** | — | A pre-approved borrowing facility from a bank. The company can draw cash when needed and repay later — acts as emergency liquidity. |
| **Cash Runway** | — | How many weeks the company can survive at its current cash burn rate before running out of money. |
| **Dept Drift** | Department Drift | A simulation parameter controlling how self-serving department proposals are. Higher drift = more proposals that benefit the department but hurt the company. |

---

## Quickstart

### Installation

```bash
pip install -e .                  # core environment only
pip install -e ".[eval]"          # + anthropic/openai for frontier eval
pip install -e ".[dev]"           # + pytest for development
```

Requires Python >= 3.10.

### Run Baselines

```bash
python -m eval.cli baselines --seeds 42 43 44 45 46 --difficulty medium --weeks 12
```

### Run a Frontier Model

```bash
export ANTHROPIC_API_KEY=sk-...
python -m eval.cli frontier --model claude-sonnet-4-6 --seeds 42 43 44 --difficulty easy
```

### Single Episode Trace

```bash
python -m eval.cli trace --policy heuristic --seed 42 --out trace.json
```

### Python API

```python
from retailceo.models import BenchmarkConfig, CEOAction, ProposalDecision
from retailceo.environment import RetailCEOEnv

env = RetailCEOEnv(BenchmarkConfig(difficulty="medium", weeks_per_quarter=12))
obs = env.reset(seed=42)

while not obs.done:
    decisions = [
        ProposalDecision(proposal_id=p.proposal_id, verdict="approve", reasoning="LGTM")
        for p in obs.inbox
    ]
    action = CEOAction(action_type="decide", decisions=decisions)
    obs = env.step(action)

print(f"Total reward: {sum(w.weekly_reward for w in env.state.history):.2f}")
```

---

## How It Works

### Simulation

Each week the CEO receives:
- **KPI dashboard** — revenue, margins, stockout rate, NPS, cash position, delivery SLA
- **Department inbox** — 6-12 proposals from Supply Chain, Store Ops, Finance, and Growth
- **Crisis alerts** — Diwali surge, monsoon floods, competitor (JioMart) entry
- **Competitor intelligence** — price cuts, dark store openings, loyalty pushes
- **Franchise complaints** — triggered by stockouts, poor SLA, low NPS

The CEO must decide on each proposal: `approve | reject | modify | request_info`.

### Reward

**Weekly (per step):**
```
R_weekly = 0.25 * kpi_delta_score - 0.05 * stockout_penalty - 0.05 * cash_pressure_penalty
```

**Terminal (episode end):**
```
R_terminal = 0.70 * quarterly_pnl_bonus - 0.60 * cash_floor_penalty
```

Total episode reward = sum of weekly rewards + terminal reward.

### Difficulty Levels

| Level | Dept Drift | Effect |
|-------|-----------|--------|
| Easy | 0.05 | Departments mostly aligned; proposals are mostly helpful |
| Medium | 0.15–0.30 | Mixed quality; some self-serving proposals need filtering |
| Hard | 0.60–0.85 | Majority adversarial; approving blindly destroys EBITDA (-15%) |

### Key Decision Levers

1. **PO quantity modification** — trim procurement to manage cash vs. risk stockouts
2. **Campaign timing** — launch during festivals for 1.8x revenue synergy
3. **Crisis preparation** — pre-position inventory before Diwali surge / monsoon
4. **Strategic opportunities** — rare (10%/week) high-ROI proposals with outsized returns
5. **Cash management** — line of credit draws, capex approvals, budget reallocation

---

## Project Structure

```
retailceo-bench/
├── retailceo/                  # Core simulation package
│   ├── models.py               # Pydantic schemas (Action, Observation, State)
│   ├── economics.py            # Business constants, festival calendar, SKU catalogue
│   ├── environment.py          # Main env: reset() / step()
│   ├── ledger.py               # Company state mutations, proposal execution
│   ├── demand.py               # Demand generation, NPS, competitor effects
│   ├── crises.py               # Crisis scheduling and lifecycle
│   ├── departments.py          # Department proposal generators (4 depts)
│   ├── grader.py               # Reward computation
│   └── prompts.py              # Observation→text rendering, response→action parsing
│
├── eval/                       # Evaluation harness
│   ├── policies.py             # Random, AllApprove, Heuristic, Oracle baselines
│   ├── frontier.py             # Anthropic/OpenAI model wrapper
│   ├── runner.py               # Multi-seed episode runner + result aggregation
│   └── cli.py                  # CLI: baselines | frontier | trace | compare
│
├── tests/                      # Test suite
├── pyproject.toml              # Package definition
└── README.md
```

---

## Roadmap / TODO

> Items needed before a public release. Contributions welcome.

### Must Have

- [x] **Test suite** — deterministic seed replay, reward bounds, KPI delta correctness, crisis activation/expiry, cash floor penalty, proposal execution for each action type (127 tests)
- [x] **Deterministic reproducibility guarantee** — hardcoded reference values for seed=42 approve-all and reject-all episodes; CI verifies exact match on Linux + macOS, Python 3.10–3.12
- [x] **LICENSE file** — MIT
- [x] **`.gitignore`** — Python defaults + egg-info + trace JSON artifacts
- [x] **Git repository init** — `git init`, initial commit, GitHub remote
- [x] **CI/CD** — GitHub Actions: pytest across Python 3.10–3.12 on push/PR
- [ ] **Leaderboard with more models** — GPT-4o, GPT-4.1, Gemini 2.5 Pro, Llama 4, open-weight models
- [x] **Standardized evaluation protocol** — lite (5 seeds, medium) and full (10 seeds, 3 difficulties) tiers with `--protocol` CLI flag
- [ ] **Human baseline** — have 3-5 humans play the benchmark to establish human-level performance
- [ ] **Result artifacts** — canonical JSON results for every leaderboard entry committed to `results/` directory
- [ ] **Clean up scratch files** — remove `run_smoke.py`, `baseline_seed42.json`, `haiku_smoke.json`, `sonnet_smoke.json`, `sonnet_trace.json` from repo root

### Should Have

- [ ] **Paper / technical report** — benchmark motivation, environment design, reward calibration, baseline analysis (arXiv preprint)
- [ ] **BibTeX citation block** — in README for academic use
- [ ] **Reward calibration analysis** — verify reward weights produce meaningful separation between policies; document sensitivity to weight changes
- [ ] **Multi-year evaluation** — standardize 1-year and 5-year protocol; current 52-week runs show divergence between models (Opus stable, Sonnet collapses)
- [ ] **Trace visualization** — script or notebook to plot KPI trajectories, cash flow, stockout rate, NPS over time from trace JSON
- [ ] **Example notebook** — Jupyter notebook walking through a single episode with commentary
- [ ] **`compare` subcommand** — flesh out the CLI compare tool with proper table formatting, statistical significance tests (bootstrap CI)
- [ ] **Token usage tracking** — report prompt/completion tokens per episode for cost comparison
- [ ] **Prompt sensitivity analysis** — test whether results change significantly with prompt variations (system prompt wording, JSON schema changes)

### Nice to Have

- [ ] **Docker image** — containerized evaluation for reproducibility
- [ ] **HuggingFace dataset card** — publish environment config + canonical traces to HF Hub
- [ ] **Gym/Gymnasium wrapper** — `gymnasium.Env` interface for RL training
- [ ] **Multi-agent variant** — separate LLM per department (4 dept heads + 1 CEO)
- [ ] **Difficulty auto-calibration** — adaptive difficulty that targets a specific reward band
- [ ] **Web UI / dashboard** — interactive single-episode player for demos
- [ ] **Contribution guide** — `CONTRIBUTING.md` with PR standards, code style, test requirements
- [ ] **Additional domains** — adapt the framework to other verticals (manufacturing, SaaS, healthcare)

---

## Environment Details

### Business Context

- **Company:** Tier-2 Indian retail chain (100 stores across 8 cities)
- **Starting cash:** ₹20 Crore (~$2.4M)
- **Weekly revenue baseline:** ₹5 Crore (~$600K)
- **SKU catalogue:** 8 categories (wheat flour, rice, oil, soap, detergent, milk, bread, batteries)
- **Category margins:** grocery staple 5%, FMCG 15%, fresh 20%, household 12%

### Crisis Events

| ID | Crisis | Timing | Effect |
|----|--------|--------|--------|
| C1 | Diwali Demand Surge | Mid-quarter | 1.3-1.5x demand, supply strain |
| C2 | Monsoon Flooding | Early quarter | Supply disruption, SLA drops |
| C3 | JioMart City Entry | Variable | 5-15% footfall drain over weeks |

### Festival Calendar

Dussehra, Diwali, Chhath Puja, Christmas, New Year — each with demand multipliers affecting specific SKU categories.

---

## Evaluation Protocol

Two tiers are available depending on cost/time budget:

### Lite (quick comparison, ~50 LLM calls)

| Parameter | Value |
|-----------|-------|
| **Seeds** | 42, 43, 44, 45, 46 (5 seeds) |
| **Difficulty** | medium only |
| **Episode length** | 12 weeks |
| **Report** | mean ± stderr of total reward, EBITDA%, stockout%, NPS, FCF |

```bash
python -m eval.cli frontier --model <model> --protocol lite
```

### Full (official leaderboard submission, ~150 LLM calls)

| Parameter | Value |
|-----------|-------|
| **Seeds** | 42, 43, 44, 45, 46, 47, 48, 49, 50, 51 (10 seeds) |
| **Difficulty** | easy, medium, hard (all three) |
| **Episode length** | 12 weeks |
| **Report** | mean ± stderr per difficulty + overall average |

```bash
python -m eval.cli frontier --model <model> --protocol full
```

### Rules for submission

1. **Temperature:** 0.0 (greedy decoding)
2. **No retries:** if the model produces an unparseable response, the fallback action (request_info for all proposals) is used — do not retry
3. **Traces:** submit full trace JSONs for independent verification
4. **System prompt:** use the default prompt from `retailceo/prompts.py` — no custom system prompts or few-shot examples

---

## Known Limitations

1. **Heuristic ceiling** — the hand-crafted Heuristic baseline currently beats all frontier models, suggesting the benchmark may reward conservative play disproportionately or that current LLMs lack multi-objective balancing for business decisions
2. **Prompt sensitivity** — results are sensitive to system prompt wording (e.g., adding `modify` examples improved Sonnet's use of `modified_params` from 33% to 100%)
3. **Single-player** — no negotiation, delegation, or multi-agent dynamics
4. **Simplified economics** — no supply chain lead times, no regional pricing, no competitor counter-moves to CEO actions
5. **No partial observability** — CEO sees all KPIs with perfect accuracy (no reporting delays or errors)

---

## Live Office Demo

This repo also ships a **live, CPU-only, key-free dashboard** — the "Pixel CEO Office" —
packaged as a Hugging Face **Docker** Space (`sdk: docker`, `app_port: 7860`). It streams
a real `RetailCEOEnv` episode driven by a scripted policy into a React 19 + PixiJS 8 SPA.

<p align="center">
  <img src="assets/office-kpis.png" alt="Top KPI bar — Week of 12 showing EBITDA, Revenue, Cash, Stock-out, NPS, and weekly Reward, each with week-over-week deltas" width="860">
</p>

<p align="center"><em>The full-width top KPI bar: quarter-to-date EBITDA &amp; revenue, cash, stock-out rate, NPS, and weekly reward — each with ▲/▼ week-over-week deltas.</em></p>

- **Backend:** [`office_api/`](./office_api/) — single-process FastAPI. Instantiates
  `RetailCEOEnv`, runs a scripted `.act()` → `env.step()` loop over the configured weeks,
  and streams UI events over a WebSocket.
- **Frontend:** [`office/frontend/`](./office/frontend/) — prebuilt bundle committed at
  `office/frontend/dist` (no Node build stage in the image).
- **Policies exposed:** `heuristic`, `oracle`, `all_approve`, `random` (scripted only —
  no frontier API, no trained checkpoint).
- **Run config:** `{ seed, policy, difficulty (easy|medium|hard), weeks (default 12) }`.

### Run the Office locally

```bash
pip install -r requirements.txt
python -m uvicorn office_api.app:app --host 0.0.0.0 --port 7860 \
  --ws-ping-interval 300 --ws-ping-timeout 300
# open http://localhost:7860
```

### API / event shapes

- `GET  /api/health` → `{ "status": "ok" }`
- `POST /api/runs` with the run config → `{ run_id, status, config }`
- `GET  /api/runs/{run_id}` → current run state + buffered events
- `WS   /api/runs/{run_id}/stream` → `run_started` → (`week_started` → `agent_thinking`
  → `agent_called` → `week_completed`) × weeks → `run_completed` (or `run_failed`)

See [`office/README.md`](./office/README.md) for the full frontend dev/build workflow.
