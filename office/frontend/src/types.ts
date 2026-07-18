export type Verdict =
  | "approve"
  | "reject"
  | "modify"
  | "request_info"
  | string;

export type Proposal = {
  proposal_id: string;
  dept: string;
  action: string;
  params: Record<string, unknown>;
  cost_inr: number;
  urgency: "low" | "med" | "high" | string;
  reasoning: string;
  week_submitted: number;
};

export type ProposalDecision = {
  proposal_id: string;
  verdict: Verdict;
  modified_params?: Record<string, unknown>;
  reasoning?: string;
};

export type Difficulty = "easy" | "medium" | "hard";

export type PolicyKind = "heuristic" | "oracle" | "all_approve" | "random";

export type KpiSnapshot = {
  revenue_inr?: number;
  gross_margin_pct?: number;
  stockout_rate_pct?: number;
  nps?: number;
  cash_inr?: number;
  delivery_sla_hit_rate_pct?: number;
};

export type PnlSnapshot = {
  revenue_qtd_inr?: number;
  cogs_qtd_inr?: number;
  opex_qtd_inr?: number;
  ebitda_qtd_inr?: number;
  ebitda_margin_pct?: number;
  cash_delta_qtd_inr?: number;
};

export type WeekPayload = {
  week: number;
  day_of_quarter?: number;
  active_crises: string[];
  inbox: Proposal[];
  decisions?: ProposalDecision[];
  budget_allocations?: Record<string, number>;
  journal?: string;
  reward?: number;
  decision_kpi?: KpiSnapshot;
  decision_pnl_qtd?: PnlSnapshot;
  kpi?: KpiSnapshot;
  pnl_qtd?: PnlSnapshot;
  cash_inr?: number;
};

export type RunConfig = {
  seed: number;
  policy: PolicyKind;
  difficulty: Difficulty;
  weeks: number;
};

export type OfficeEvent = {
  type:
    | "run_started"
    | "week_started"
    | "agent_thinking"
    | "agent_called"
    | "week_completed"
    | "run_completed"
    | "run_failed";
  run_id: string;
  ts?: number;
  payload: Record<string, unknown>;
};

