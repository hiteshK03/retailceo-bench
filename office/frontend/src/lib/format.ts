import type { ProposalDecision, Verdict } from "../types";

export function formatInr(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(1)}L`;
  return `${sign}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function formatNumber(value?: number, digits = 1): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
}

export function verdictLabel(verdict?: Verdict): string {
  if (!verdict) return "pending";
  return verdict.replace("_", " ");
}

export function verdictClass(verdict?: Verdict): string {
  if (verdict === "approve") return "approve";
  if (verdict === "reject") return "reject";
  if (verdict === "flag_suspicious") return "flag";
  if (verdict === "modify") return "modify";
  if (verdict === "request_info") return "info";
  return "pending";
}

export function decisionsById(decisions: ProposalDecision[] = []): Record<string, ProposalDecision> {
  return Object.fromEntries(decisions.map((decision) => [decision.proposal_id, decision]));
}

