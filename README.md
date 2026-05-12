# RetailCEO-Bench

**Can LLMs run a retail chain profitably?**

RetailCEO-Bench is an evaluation benchmark that tests how well large language models can operate as CEO of a simulated tier-2 Indian retail chain over a 12-week quarter (or multi-year horizon). The LLM receives weekly KPI reports, department proposals, crisis alerts, and competitor intelligence, then must make approval/rejection/modification decisions that keep the company profitable, solvent, and growing.

---

## Leaderboard (13-Week, 3 Seeds)

| Policy | Easy | Medium | Hard | Avg |
|--------|------|--------|------|-----|
| Oracle (peek at crises) | +2.56 | +1.86 | +0.72 | +1.71 |
| Heuristic (19 rules) | +2.13 | +1.55 | +0.33 | +1.34 |
| **Claude Opus 4.7** | +1.47 | +0.75 | -0.30 | +0.64 |
| **Claude Sonnet 4** | +1.44 | +0.90 | +0.01 | +0.78 |
| All-Approve | +1.08 | +0.52 | -0.45 | +0.38 |
| Random | -0.32 | -0.89 | -1.67 | -0.96 |

> **Reward range:** theoretical [-4.5, +3.5]. Higher is better.
> Frontier models currently underperform the hand-crafted Heuristic baseline — closing this gap is the benchmark's core challenge.

<details>
<summary>Extended metrics (click to expand)</summary>

| Policy | Difficulty | Reward | EBITDA% | Stockout% | NPS | FCF (Cr) |
|--------|-----------|--------|---------|-----------|-----|----------|
| Opus 4.7 | Easy | +1.47 | +7.75 | 7.4 | 27.7 | +21.4 |
| Opus 4.7 | Medium | +0.75 | +1.85 | 7.9 | 27.0 | +16.7 |
| Opus 4.7 | Hard | -0.30 | -2.00 | 7.3 | 26.8 | +14.4 |
| Sonnet 4 | Easy | +1.44 | +7.31 | 6.5 | 28.4 | +23.0 |
| Sonnet 4 | Medium | +0.90 | +3.81 | 8.3 | 25.8 | +26.0 |
| Sonnet 4 | Hard | +0.01 | -1.15 | 5.3 | 28.1 | +17.2 |

**1-Year Easy (1 seed):**
| Policy | Reward | EBITDA% | Stockout% | NPS | FCF (Cr) |
|--------|--------|---------|-----------|-----|----------|
| Opus 4.7 | +1.35 | +5.61 | 7.5 | 25.7 | +21.9 |
| Sonnet 4 | +0.48 | +2.30 | 11.6 | 19.1 | +50.9 |

</details>

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
| Hard | 0.35–0.55 | Significant noise; many proposals hurt the company |

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

- [ ] **Test suite** — deterministic seed replay, reward bounds, KPI delta correctness, crisis activation/expiry, cash floor penalty, proposal execution for each action type
- [ ] **Deterministic reproducibility guarantee** — verify `reset(seed=42)` + 12 identical actions = identical total reward across platforms (Linux/macOS, Python 3.10–3.12)
- [ ] **LICENSE file** — choose and add (MIT or Apache-2.0)
- [ ] **`.gitignore`** — Python defaults + egg-info + trace JSON artifacts
- [ ] **Git repository init** — `git init`, initial commit, remote setup
- [ ] **CI/CD** — GitHub Actions: lint (ruff), type-check (mypy/pyright), test (pytest), pip install smoke test
- [ ] **Leaderboard with more models** — GPT-4o, GPT-4.1, Gemini 2.5 Pro, Llama 4, open-weight models
- [ ] **Standardized evaluation protocol** — document exact seed set (e.g., 42–51), difficulty, weeks, and number of runs required for official leaderboard submission
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
- **SKU catalogue:** 8 categories (atta, rice, oil, soap, detergent, milk, bread, batteries)
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

## Evaluation Protocol (Draft)

For reproducible leaderboard submissions:

1. **Seeds:** 42, 43, 44, 45, 46 (5 seeds minimum)
2. **Difficulties:** easy, medium, hard (report all three)
3. **Episode length:** 13 weeks (default quarter)
4. **Report:** mean ± std of total reward, plus EBITDA%, stockout%, NPS, FCF
5. **Traces:** submit full trace JSONs for verification

---

## Known Limitations

1. **Heuristic ceiling** — the hand-crafted Heuristic baseline currently beats all frontier models, suggesting the benchmark may reward conservative play disproportionately or that current LLMs lack multi-objective balancing for business decisions
2. **Prompt sensitivity** — results are sensitive to system prompt wording (e.g., adding `modify` examples improved Sonnet's use of `modified_params` from 33% to 100%)
3. **Single-player** — no negotiation, delegation, or multi-agent dynamics
4. **Simplified economics** — no supply chain lead times, no regional pricing, no competitor counter-moves to CEO actions
5. **No partial observability** — CEO sees all KPIs with perfect accuracy (no reporting delays or errors)
