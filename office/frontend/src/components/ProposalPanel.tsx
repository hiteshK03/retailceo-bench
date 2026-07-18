import type { Proposal, ProposalDecision, WeekPayload } from "../types";
import { decisionsById, formatInr, verdictClass, verdictLabel } from "../lib/format";

type Props = {
  week?: WeekPayload;
};

const DEPT_LABELS: Record<string, string> = {
  supply_chain: "Supply Chain",
  store_ops: "Store Ops",
  finance: "Finance",
  growth: "Growth",
};

export function ProposalPanel({ week }: Props) {
  const decisions = decisionsById(week?.decisions);
  const grouped = groupByDept(week?.inbox ?? []);
  const departments = Object.keys(grouped).sort((a, b) => a.localeCompare(b));

  return (
    <aside className="proposal-panel panel pixel-border">
      <div className="panel-title">Department Proposals</div>
      {departments.length === 0 ? (
        <p className="empty-copy">No proposals loaded yet.</p>
      ) : (
        departments.map((dept) => (
          <section className="dept-group" key={dept}>
            <h3>{DEPT_LABELS[dept] ?? dept}</h3>
            {grouped[dept].map((proposal) => (
              <ProposalCard
                key={proposal.proposal_id}
                proposal={proposal}
                decision={decisions[proposal.proposal_id]}
              />
            ))}
          </section>
        ))
      )}
    </aside>
  );
}

function ProposalCard({
  proposal,
  decision,
}: {
  proposal: Proposal;
  decision?: ProposalDecision;
}) {
  const verdict = decision?.verdict;
  const params = Object.entries(proposal.params ?? {})
    .filter(([, value]) => value !== null && value !== "" && value !== undefined)
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`);

  return (
    <article className={`proposal-card ${verdictClass(verdict)} ${proposal.urgency}`}>
      <div className="proposal-card-header">
        <strong>{proposal.proposal_id}</strong>
        <span>{proposal.action}</span>
      </div>
      <div className="proposal-meta">
        <span>{proposal.urgency}</span>
        <span>{formatInr(proposal.cost_inr)}</span>
      </div>
      <p>{proposal.reasoning}</p>
      {params.length > 0 && <code>{params.join(" | ")}</code>}
      <div className="verdict-row">
        <span className={`verdict-pill ${verdictClass(verdict)}`}>{verdictLabel(verdict)}</span>
      </div>
      {decision?.reasoning && <small>{decision.reasoning}</small>}
    </article>
  );
}

function groupByDept(proposals: Proposal[]): Record<string, Proposal[]> {
  return proposals.reduce<Record<string, Proposal[]>>((acc, proposal) => {
    acc[proposal.dept] = acc[proposal.dept] ?? [];
    acc[proposal.dept].push(proposal);
    return acc;
  }, {});
}

