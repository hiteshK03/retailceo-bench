"""Observation -> prompt, response -> CEOAction.

The prompt is the full weekly brief the CEO sees.  The response is
expected to be a JSON object we parse back into a CEOAction.  Kept
deterministic and dependency-free so SFT/GRPO training, vLLM inference, and
the unit tests all share the same serialisation.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from retailceo.models import (
    CEOAction,
    CEOObservation,
    KPISnapshot,
    Proposal,
    ProposalDecision,
)


SYSTEM_PROMPT = """You are the CEO of a tier-2 Indian retail chain (30 stores across 3 cities).
Each week your 4 departments (supply_chain, store_ops, finance, growth) submit proposals.
You must approve, reject, modify, or request_info for each one, allocate department budgets, and write a short founder's journal entry.

Your goal is to maximise quarterly EBITDA while:
- Keeping stockouts below 8% and NPS above 35.
- Not running out of cash (INR 0 floor).
- Using inventory, pricing, staffing, marketing, and financing decisions to operate the business profitably.

IMPORTANT: When you "modify" a proposal, you MUST include "modified_params" with the changed values — otherwise the original params are used unchanged.
For PO proposals (po.place, po.bulk_deal), you can modify "qty" to control procurement volume. This is your primary lever to manage cash flow.

RESPONSE FORMAT: a single valid JSON object inside <action>...</action> tags:
<action>
{
  "decisions": [
    {"proposal_id": "S01-01", "verdict": "modify", "modified_params": {"qty": 80000}, "reasoning": "reduce PO qty from 120000 to 80000 to preserve cash while maintaining adequate stock"},
    {"proposal_id": "G01-02", "verdict": "approve", "reasoning": "campaign ROI is strong during festival week"},
    {"proposal_id": "G01-04", "verdict": "reject", "reasoning": "deep discount would destroy margin while cash is tight"}
  ],
  "budget_allocations": {"supply_chain": 10000000, "store_ops": 2000000, "finance": 1000000, "growth": 2000000},
  "journal_entry": "Week 1: trimmed PO quantities to preserve working capital; approved festival campaign for demand uplift; cash 25 Cr, NPS 37."
}
</action>

Verdicts must be one of: approve, reject, modify, request_info."""


# ---------------------------------------------------------------------------
# Two-pass prompts: action head (JSON only) + journal head (free text).
# Used by DualHeadCEO at inference and the decoupled SFT-journal / GRPO-action
# training pipeline.  Each head gets its own output budget so one doesn't
# truncate the other.
# ---------------------------------------------------------------------------

ACTION_SYSTEM_PROMPT = """You are the CEO of a tier-2 Indian retail chain.
Each week you must decide on the inbox of proposals from 4 departments (supply_chain, store_ops, finance, growth) and allocate budgets.

Your goal is to maximise quarterly EBITDA while:
- Keeping stockouts below 8% and NPS above 35.
- Not running out of cash (INR 0 floor).
- Using inventory, pricing, staffing, marketing, and financing decisions to operate the business profitably.

IMPORTANT: When you "modify" a proposal, you MUST include "modified_params" with the changed values — otherwise the original params are used unchanged.
For PO proposals (po.place, po.bulk_deal), you can modify "qty" to control procurement volume. This is your primary lever to manage cash flow.

OUTPUT FORMAT -- a single JSON object inside <action>...</action> tags. NO prose, NO journal, NO analysis before or after. JSON only.
<action>
{
  "decisions": [
    {"proposal_id": "S01-01", "verdict": "modify", "modified_params": {"qty": 80000}, "reasoning": "reduce PO qty to preserve cash"},
    {"proposal_id": "G01-02", "verdict": "approve"},
    {"proposal_id": "G01-04", "verdict": "reject", "reasoning": "deep discount would destroy margin while cash is tight"}
  ],
  "budget_allocations": {"supply_chain": 10000000, "store_ops": 2000000, "finance": 1000000, "growth": 2000000}
}
</action>

Verdicts: approve | reject | modify | request_info.
The journal will be written separately; do not include it here."""


ACTION_SYSTEM_PROMPT_PERMISSIVE = """You are the CEO of a tier-2 Indian retail chain.
Each week you decide on the inbox of proposals from 4 departments
(supply_chain, store_ops, finance, growth) and allocate budgets.

Your goal is to maximise quarterly EBITDA while:
- Keeping stockouts below 8% and NPS above 35.
- Not running out of cash (INR 0 floor).
- Using inventory, pricing, staffing, marketing, and financing decisions to operate the business profitably.

You MAY deliberate out loud first.  Start with a short <thinking>...</thinking>
block walking through the inbox (1-2 sentences per proposal is enough), then
commit to a single JSON object inside <action>...</action> tags.  Only the
<action> block is graded, so prose outside it costs tokens but is otherwise
free.

BUDGET GUIDANCE -- typical healthy weekly split of a ~INR 15-20 Cr pool is
roughly supply_chain 55-65 %, growth 12-18 %, store_ops 10-15 %, finance
5-8 %.  Starving supply_chain is the #1 cause of stockouts and EBITDA loss;
default to a generous supply_chain allocation unless stockout is already
<= 2 %.

VERDICTS: approve | reject | modify | request_info.

OUTPUT FORMAT example:
<thinking>
S01-01 routine wheat flour restock, qty in-line, approve.
G01-04 discount 30% on staples, hurts margin, reject.
Stockout 4% trailing -> over-weight supply_chain this week.
</thinking>
<action>
{
  "decisions": [
    {"proposal_id": "S01-01", "verdict": "modify", "modified_params": {"qty": 85000}, "reasoning": "trim PO to 85% to preserve cash"},
    {"proposal_id": "G01-02", "verdict": "approve"},
    {"proposal_id": "G01-04", "verdict": "reject"}
  ],
  "budget_allocations": {"supply_chain": 12000000, "store_ops": 2000000, "finance": 800000, "growth": 2500000}
}
</action>

When using "modify", you MUST include "modified_params" with the actual changed values.
For PO proposals, modifying "qty" is your primary lever to manage cash flow and working capital.

The journal is written in a separate call; do not include it here."""


JOURNAL_SYSTEM_PROMPT = """You are the CEO of a retail chain writing your weekly founder's journal.

You have just made this week's decisions (listed below). Write a concise, structured retrospective (100-250 words) covering:
- which proposals you approved, modified, requested info on, or rejected (reference their IDs)
- KPI trajectory: cash, margin, NPS, stockout, SLA
- risks and next-week priorities
- all four department names (supply_chain, store_ops, finance, growth)
- continuity: echo a theme or proposal from last week's journal if applicable

OUTPUT FORMAT -- the journal text only inside <journal>...</journal> tags. No JSON, no decisions, no preamble.
<journal>
Week N: prioritised supply_chain restock before festival demand; rejected a margin-dilutive discount; approved O01-04 weekend staffing.
Cash 13 Cr, NPS 37 (d+1), stockout 2% (d-1pp). Supply chain lane on plan. Risks: monsoon route still slow.
Next week: monitor Chhath supply chain, sell-through, and working-capital runway.
</journal>"""


# ---------------------------------------------------------------------------
# Observation -> prompt
# ---------------------------------------------------------------------------

def render_inbox(inbox: List[Proposal]) -> str:
    lines: List[str] = []
    for p in inbox:
        params_str = ", ".join(f"{k}={v!r}" for k, v in (p.params or {}).items())
        reason = f"  reasoning: {p.reasoning}" if p.reasoning else ""
        lines.append(
            f"- [{p.proposal_id}] {p.dept}.{p.action} (urgency={p.urgency}, "
            f"cost_inr=INR{p.cost_inr:+,.0f}){reason}\n"
            f"    params: {params_str}"
        )
    return "\n".join(lines)


def render_kpi(kpi: KPISnapshot) -> str:
    runway = (
        f"{kpi.cash_runway_weeks:.1f}w"
        if kpi.cash_runway_weeks is not None
        else "stable"
    )
    return (
        f"revenue_last_week=INR{kpi.revenue_inr/1e7:.2f}Cr "
        f"(d {kpi.revenue_delta_pct:+.1f}%) | "
        f"gross_margin={kpi.gross_margin_pct:.2f}% (d{kpi.margin_delta_pts:+.2f}pp) | "
        f"stockout={kpi.stockout_rate_pct:.1f}% (d{kpi.stockout_delta_pts:+.2f}pp) | "
        f"NPS={kpi.nps:.0f} (d{kpi.nps_delta:+.1f}) | "
        f"SLA={kpi.delivery_sla_hit_rate_pct:.0f}% (d{kpi.sla_delta_pts:+.1f}pp) | "
        f"cash=INR{kpi.cash_inr/1e7:+.2f}Cr (dINR{kpi.cash_delta_inr/1e7:+.2f}Cr, "
        f"burn=INR{kpi.cash_burn_rate_inr_per_week/1e7:.2f}Cr/wk, "
        f"runway={runway}, pressure={kpi.cash_pressure_score:.2f}, "
        f"streak={kpi.cash_pressure_streak_weeks}w) | "
        f"basket=INR{kpi.basket_size_inr:.0f} | "
        f"repeat={kpi.repeat_purchase_rate_pct:.0f}%"
    )


def render_observation(
    obs: CEOObservation,
    token_budget: Optional[int] = None,
) -> str:
    """Render the full weekly prompt the CEO sees.

    If ``token_budget`` is set, append a short note reminding the model that
    its response will be truncated beyond that many tokens.  This mirrors the
    hard cap the environment imposes on the trained policy (``max_new_tokens``
    in the GRPO loop), so external baselines face the same constraint.
    """
    parts: List[str] = []
    parts.append(
        f"=== RetailCEO -- Week {obs.week_of_quarter}/13 (day {obs.day_of_quarter}/90) ==="
    )
    if obs.message:
        parts.append(f"Narrative: {obs.message}")
    parts.append(f"KPIs: {render_kpi(obs.kpi_snapshot)}")

    pnl = obs.pnl_snapshot
    parts.append(
        f"P&L QTD: revenue INR{pnl.revenue_qtd_inr/1e7:.2f}Cr, "
        f"EBITDA INR{pnl.ebitda_qtd_inr/1e7:+.2f}Cr ({pnl.ebitda_margin_pct:+.1f}%)."
    )

    if obs.active_crises:
        crisis_lines = "\n".join(
            f"  * {c.crisis_id} {c.name} (severity={c.severity}, duration_days={c.duration_days}) -- {c.description}"
            for c in obs.active_crises
        )
        parts.append(f"Active crises:\n{crisis_lines}")

    if obs.franchise_complaints:
        hi = sum(1 for c in obs.franchise_complaints if c.severity == "high")
        md = sum(1 for c in obs.franchise_complaints if c.severity == "med")
        lo = sum(1 for c in obs.franchise_complaints if c.severity == "low")
        sample = "; ".join(
            f"{c.city}/{c.franchise_id}: {c.issue}"
            for c in obs.franchise_complaints[:3]
        )
        parts.append(
            f"Franchise complaints ({hi} high, {md} med, {lo} low): {sample}"
            + (" ..." if len(obs.franchise_complaints) > 3 else "")
        )

    if obs.competitor_events:
        comp_lines = "; ".join(e.description for e in obs.competitor_events[-4:])
        parts.append(f"Recent competitor signals: {comp_lines}")

    if obs.last_journal:
        # Compress the prior-week journal to ~60 words to save prompt budget
        # while preserving enough nouns for journal-coherence continuity.
        parts.append(f"Prior-week journal (excerpt): {_compress_journal(obs.last_journal, max_words=60)}")
    parts.append(f"\nINBOX ({len(obs.inbox)} proposals):\n{render_inbox(obs.inbox)}")
    parts.append(
        "\nReturn your weekly decision as a single JSON object wrapped in <action>...</action> tags."
    )
    if token_budget is not None:
        parts.append(
            f"HARD BUDGET: the environment will truncate your response after "
            f"{token_budget} output tokens -- if the closing </action> tag is missing, "
            f"your action is treated as malformed and the environment falls back to "
            f"approve-all (cash and stockouts can drift). Skip preamble/analysis; emit JSON only."
        )
    return "\n\n".join(parts)


def build_chat(
    obs: CEOObservation,
    token_budget: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Standard HF chat template (system + user).

    ``token_budget`` is forwarded to :func:`render_observation`.  Callers that
    want to train/evaluate under the same output-length budget the trainer
    imposes should pass it (it's a no-op for the 1.5B training flow, which
    uses ``token_budget=None`` so the SFT/GRPO prompt distribution is stable).
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": render_observation(obs, token_budget=token_budget)},
    ]


def build_action_chat(
    obs: CEOObservation,
    token_budget: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Chat template for the action head (JSON only, no journal).

    Used by DualHeadCEO and by the action-only GRPO refactor in train.py.
    """
    return [
        {"role": "system", "content": ACTION_SYSTEM_PROMPT},
        {"role": "user", "content": render_observation(obs, token_budget=token_budget)},
    ]


def build_journal_chat(
    obs: CEOObservation,
    decisions: List[ProposalDecision],
    budget_allocations: Optional[Dict[str, float]] = None,
) -> List[Dict[str, str]]:
    """Chat template for the journal head (free text, 150-350 words).

    The journal head receives the decisions the action head just made, so it
    can reference specific proposal IDs for the ``journal_coherence`` score.
    This mirrors how a human CEO would write a retrospective AFTER making the
    week's calls, not in parallel with them.
    """
    obs_text = render_observation(obs, token_budget=None)
    decision_lines: List[str] = []
    for d in decisions:
        piece = f"  - {d.proposal_id}: {d.verdict}"
        if d.reasoning:
            piece += f" ({d.reasoning})"
        decision_lines.append(piece)
    budget_str = ""
    if budget_allocations:
        budget_str = "\nBudget allocations (INR): " + ", ".join(
            f"{k}={int(v):,}" for k, v in budget_allocations.items()
        )
    user_content = (
        f"{obs_text}\n\n"
        f"DECISIONS YOU JUST MADE THIS WEEK:\n" + "\n".join(decision_lines)
        + budget_str
        + "\n\nNow write the founder's journal entry for this week inside "
          "<journal>...</journal> tags (150-350 words)."
    )
    return [
        {"role": "system", "content": JOURNAL_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


_JOURNAL_TAG_RE = re.compile(r"<journal>\s*(.*?)\s*</journal>", re.DOTALL)
_JOURNAL_OPEN_RE = re.compile(r"<journal>\s*(.*)", re.DOTALL)


def parse_journal_response(text: str) -> str:
    """Extract the journal text from a journal-head completion.

    Tolerant to missing close-tag (truncation): returns what we have.
    """
    m = _JOURNAL_TAG_RE.search(text)
    if m:
        return m.group(1).strip()
    m = _JOURNAL_OPEN_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Response -> CEOAction
# ---------------------------------------------------------------------------

def _compress_journal(text: str, max_words: int = 60) -> str:
    """Return a shortened view of the previous week's journal.

    Takes the first ``max_words`` words -- short enough to fit the CEO's token
    budget, long enough to retain the noun-overlap the grader uses for
    continuity scoring.  Any proposal IDs in the original text are preserved
    by pulling them forward into the excerpt.
    """
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    head = " ".join(words[:max_words])
    pids = re.findall(r"\b[A-Z]{1,4}\d{1,2}-\d{1,2}\b", text)
    if pids:
        pids_seen = list(dict.fromkeys(pids))[:3]
        head += f"  [refs: {', '.join(pids_seen)}]"
    return head + " ..."


_ACTION_RE = re.compile(r"<action>\s*(\{.*?\})\s*</action>", re.DOTALL)
_ACTION_OPEN_RE = re.compile(r"<action>\s*(\{.*)", re.DOTALL)
_JSON_FALLBACK_RE = re.compile(r"(\{.*\})", re.DOTALL)


def _extract_json(text: str) -> Tuple[Optional[str], bool]:
    """Extract the JSON payload from a CEO completion.

    Returns (json_string, is_complete).  ``is_complete`` is False when we
    matched an <action> opening but not a matching closing tag -- this flags
    truncated completions so partial-JSON recovery can be attempted.
    """
    m = _ACTION_RE.search(text)
    if m:
        return m.group(1), True
    m = _ACTION_OPEN_RE.search(text)
    if m:
        return m.group(1), False
    m = _JSON_FALLBACK_RE.search(text)
    if m:
        return m.group(1), True
    return None, False


def _recover_partial_json(raw: str) -> Optional[Dict[str, Any]]:
    """Attempt to recover as much structure as possible from a truncated JSON blob.

    Strategy: walk backwards from the end, close unbalanced braces/brackets and
    strings, try to parse each prefix, return the first successful parse.  This
    lets us salvage decisions that *did* make it into the output before the
    600-token cap kicked in, instead of falling back to ``approve-all``.
    """
    if not raw or not raw.strip():
        return None
    # Try as-is first (fast path when the issue is a trailing stray char).
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Close any unterminated string.
    s = raw
    if s.count('"') % 2 == 1:
        s = s + '"'
    # Close any unterminated bracket stack.
    opens = []
    in_str = False
    esc = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            opens.append(ch)
        elif ch in "}]" and opens:
            opens.pop()
    closer = {"{": "}", "[": "]"}
    s_closed = s + "".join(closer[c] for c in reversed(opens))

    for candidate in (s_closed, s):
        try:
            return json.loads(candidate)
        except Exception:
            continue

    # Last resort: trim back to the last top-level comma and retry.
    depth = 0
    in_str = False
    esc = False
    last_safe = -1
    for i, ch in enumerate(raw):
        if esc:
            esc = False; continue
        if ch == "\\":
            esc = True; continue
        if ch == '"':
            in_str = not in_str; continue
        if in_str:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == "," and depth == 1:
            last_safe = i
    if last_safe > 0:
        trimmed = raw[:last_safe] + "]}"
        try:
            return json.loads(trimmed)
        except Exception:
            return None
    return None


def parse_response(
    text: str,
    inbox: List[Proposal],
    fallback_verdict: str = "request_info",
    fallback_journal: str = "",
) -> Tuple[CEOAction, Dict[str, Any]]:
    """Parse a model completion into a CEOAction.

    On parse failure / invalid JSON / missing fields, fill with SAFE defaults
    (``request_info`` -- no-op in the ledger) so a single malformed journal
    token does not cascade into approve-all -> stockouts + cash burn across
    every other reward component.  Callers that want the legacy behaviour should pass
    ``fallback_verdict="approve"`` explicitly.

    Returns:
        (action, telemetry) where telemetry has keys:
            parse_ok       : bool  (True iff JSON parsed cleanly)
            parse_partial  : bool  (True iff we recovered from truncation)
            parse_error    : Optional[str]
            n_decisions_missing : int (proposals without a decision in output)
            n_decisions_extra   : int (decisions referencing unknown ids)
            n_invalid_verdict   : int
            journal_len         : int
    """
    tel: Dict[str, Any] = {
        "parse_ok": False,
        "parse_partial": False,
        "parse_error": None,
        "n_decisions_missing": 0,
        "n_decisions_extra": 0,
        "n_invalid_verdict": 0,
        "journal_len": 0,
    }
    inbox_ids = {p.proposal_id for p in inbox}

    raw_json, is_complete = _extract_json(text)
    if raw_json is None:
        tel["parse_error"] = "no_json_block"
        return _fallback_action(inbox, fallback_verdict, fallback_journal), tel

    data: Optional[Dict[str, Any]] = None
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        recovered = _recover_partial_json(raw_json)
        if recovered is not None and isinstance(recovered, dict):
            data = recovered
            tel["parse_partial"] = True
            tel["parse_error"] = f"recovered_from:{e.msg}"
        else:
            tel["parse_error"] = f"json_error:{e.msg}"
            return _fallback_action(inbox, fallback_verdict, fallback_journal), tel

    if not isinstance(data, dict):
        tel["parse_error"] = "root_not_object"
        return _fallback_action(inbox, fallback_verdict, fallback_journal), tel

    # --- Decisions ---
    valid_verdicts = {"approve", "reject", "modify", "request_info"}
    raw_decisions = data.get("decisions", [])
    parsed_decisions: List[ProposalDecision] = []
    seen_ids: set = set()

    if not isinstance(raw_decisions, list):
        tel["parse_error"] = "decisions_not_list"
        return _fallback_action(inbox, fallback_verdict, fallback_journal), tel

    for d in raw_decisions:
        if not isinstance(d, dict):
            continue
        pid = d.get("proposal_id")
        verdict = d.get("verdict", fallback_verdict)
        if pid is None:
            continue
        if pid not in inbox_ids:
            tel["n_decisions_extra"] += 1
            continue
        if verdict not in valid_verdicts:
            tel["n_invalid_verdict"] += 1
            verdict = fallback_verdict
        kwargs: Dict[str, Any] = {"proposal_id": pid, "verdict": verdict}
        reasoning = d.get("reasoning")
        if isinstance(reasoning, str):
            kwargs["reasoning"] = reasoning
        modified_params = d.get("modified_params")
        if isinstance(modified_params, dict):
            kwargs["modified_params"] = modified_params
        parsed_decisions.append(ProposalDecision(**kwargs))
        seen_ids.add(pid)

    # Backfill decisions for any missing proposals with the caller's fallback.
    # Default ``request_info`` is a no-op in the ledger with no
    # false_reject_penalty -- breaks the truncation -> approve-all cascade.
    for p in inbox:
        if p.proposal_id not in seen_ids:
            tel["n_decisions_missing"] += 1
            parsed_decisions.append(ProposalDecision(
                proposal_id=p.proposal_id,
                verdict=fallback_verdict,
            ))

    # --- Budget allocations ---
    raw_budget = data.get("budget_allocations", {})
    budget: Dict[str, float] = {}
    if isinstance(raw_budget, dict):
        for k, v in raw_budget.items():
            if isinstance(v, (int, float)):
                budget[str(k)] = float(v)

    # --- Journal ---
    journal = data.get("journal_entry", fallback_journal)
    if not isinstance(journal, str):
        journal = fallback_journal
    tel["journal_len"] = len(journal.split())

    tel["parse_ok"] = tel["parse_ok"] or not tel["parse_partial"]

    return CEOAction(
        decisions=parsed_decisions,
        budget_allocations=budget,
        journal_entry=journal,
    ), tel


def _fallback_action(
    inbox: List[Proposal],
    fallback_verdict: str,
    fallback_journal: str,
) -> CEOAction:
    """Build a neutral action on total parse failure.

    The top-level ``fallback_verdict`` default is ``request_info`` (see
    ``parse_response``) -- a no-op in the ledger that doesn't trigger
    ``false_reject_penalty``.  This breaks the "one bad journal kills every
    reward component" cascade that plagued GRPO v5.  Callers that want the
    legacy approve-all behaviour must pass ``fallback_verdict="approve"``
    explicitly.
    """
    return CEOAction(
        decisions=[
            ProposalDecision(proposal_id=p.proposal_id, verdict=fallback_verdict)
            for p in inbox
        ],
        budget_allocations={"supply_chain": 5e6, "store_ops": 5e5, "finance": 1e6, "growth": 1e6},
        journal_entry=fallback_journal,
    )
