# Reward Calibration Notes

Why did a hand-crafted `HeuristicCEO` beat frontier LLMs on RetailCEO-Bench,
and what changed to fix the underlying benchmark defects? This note records the
diagnosis (cross-verified against the code by three independent adversarial
reviews) and the changes made in response.

## Diagnosis: it was reward structure, not information asymmetry

The tempting explanation — "the heuristic is a secret oracle that reads exact
KPI floats the LLM has to infer from text" — **does not hold**. `render_kpi`
(`retailceo/prompts.py`) prints `cash_pressure_score`, `runway`, `burn`,
`streak`, `cash`, and `gross_margin` as exact numbers, at precision sufficient
to reconstruct every threshold the heuristic branches on. The agents see the
same cash state.

The real driver is the **reward structure**:

1. **EBITDA-dominated, terminal-weighted reward.** `REWARD_WEIGHTS`
   (`retailceo/economics.py`) puts `quarterly_pnl = 0.70` — by far the largest
   term — and it is applied once at episode end (`grader.terminal_reward`).
2. **Discretionary spend routes straight into EBITDA.** `OPEX_BEARING_ACTIONS`
   (`retailceo/ledger.py`) adds approved discretionary spend to
   `opex_qtd_inr`, which subtracts from EBITDA. So approving *less* discretionary
   spend mechanically raises the dominant reward term.
3. **Some actions were strictly dominated.** `capex.approve` was pure cost with
   **zero modeled upside** — it could never be correct to approve, so the
   heuristic's blanket reject was mechanically optimal. That is not a test of
   judgement; it is a trap.
4. **`budget_allocations` was an inert decoy.** The field was only stored in
   history, never read by the simulation, yet the prompt advertised it as
   score-driving. Wasted model attention on a lever that did nothing.
5. **`Oracle == Heuristic` exactly.** The "ceiling" baseline added no headroom
   above the heuristic, so a frontier model had nothing to reach for — the
   single strongest indictment.

Confirmed empirically: the heuristic's edge over `all_approve` is ~100%
concentrated in the terminal EBITDA term; `all_approve` already scored well
(the bar was low).

## Claims that did NOT survive scrutiny

- Information asymmetry on cash fields (refuted — see above). The only genuine,
  narrow asymmetry is per-proposal reference constants (SKU catalogue costs,
  category throughput) behind two of the heuristic's PO checks — a small slice,
  not the root cause.
- `growth_lever_mult` at medium is **1.2**, not 1.0 (`economics.py`).

## Changes made

1. **`capex.approve` is now a real fast-vs-slow judgement.** A project returns
   an amortised, near-pure-margin revenue stream of
   `(amount / payback_weeks) * CAPEX_PAYBACK_UPLIFT` per week for
   `payback_weeks` weeks (`ledger.execute_approved_proposals` +
   `consume_pending_effects`). With `CAPEX_PAYBACK_UPLIFT = 2.0`, fast-payback
   projects (≲20wk) clear their cost inside a 12-week episode (+EV) while slow
   ones (≳24wk) do not (−EV). Break-even sits mid-range of the dept-generated
   12–48wk payback distribution, so it is a genuine call.
2. **`campaign.launch` effect raised** so a well-timed (festival-synergy 1.8×)
   campaign can clear its cost, instead of being ~break-even at any timing.
3. **`OracleCEO` is now a genuine ceiling.** It approves capex using
   *horizon-aware* EV — `uplift * min(weeks_left, payback) / payback > 1` — so
   it correctly declines even fast-payback capex offered too late in the
   episode. Result (10 seeds × 3 difficulties): oracle ≥ heuristic on every
   difficulty (avg +1.311 vs +1.283), biggest edge on hard where the
   heuristic's blanket capex-reject is most costly. A regression test enforces
   `oracle >= heuristic` on all difficulties.
4. **`budget_allocations` decoy neutralized.** The false "drives the score"
   claim was removed from the system prompt; the field is documented as
   optional and unscored. (The store-count prompt bug — "30 stores/3 cities" vs
   the actual 100/8 — was fixed at the same time.)
5. **`false_reject_penalty` activated** (was implemented but never wired into
   `weekly_reward`), urgency-weighted so correctly rejecting low-urgency padding
   is nearly free while rejecting genuinely urgent proposals is penalized.

## Still open

- The oracle's edge on `hard` is directional but only borderline significant
  (paired bootstrap p ≈ 0.06 at n=10). A stronger oracle (e.g. exploiting
  festival campaign timing, which currently hurts more than it helps) would
  widen the ceiling and is left as future work.
- Frontier leaderboard numbers must be re-run under the corrected reward.
