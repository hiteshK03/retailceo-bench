import type { WeekPayload } from "../types";
import type { PendingVerdict } from "../components/ProposalPanel";

/** True once every proposal in the current week's inbox has a chosen verdict. */
export function allDecided(
  week: WeekPayload | undefined,
  pending: Record<string, PendingVerdict>,
): boolean {
  const inbox = week?.inbox ?? [];
  return inbox.length > 0 && inbox.every((p) => pending[p.proposal_id] !== undefined);
}

export type WireDecision = {
  proposal_id: string;
  verdict: string;
  modified_params?: Record<string, unknown>;
};

/**
 * Assemble the decision list to send for a week. Proposals the player never
 * touched default to `request_info` (a ledger no-op), mirroring the server's
 * `build_human_action` fallback so the two sides agree.
 */
export function buildDecisions(
  week: WeekPayload | undefined,
  pending: Record<string, PendingVerdict>,
): WireDecision[] {
  return (week?.inbox ?? []).map((p) => ({
    proposal_id: p.proposal_id,
    verdict: pending[p.proposal_id]?.verdict ?? "request_info",
    modified_params: pending[p.proposal_id]?.modified_params,
  }));
}
