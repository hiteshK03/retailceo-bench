import type { KpiSnapshot } from "../types";
import { formatInr } from "../lib/format";

type Props = {
  journal?: string;
  statusMessage: string;
  decisionKpi?: KpiSnapshot;
};

export function JournalPanel({ journal, statusMessage, decisionKpi }: Props) {
  return (
    <aside className="journal-panel panel pixel-border">
      <div className="panel-title">CEO Journal</div>
      <div className="agent-status">{statusMessage}</div>
      {decisionKpi && (
        <div className="journal-context">
          Journal snapshot: CEO saw cash {formatInr(decisionKpi.cash_inr)}, NPS{" "}
          {decisionKpi.nps?.toFixed(1) ?? "-"}, stockout{" "}
          {decisionKpi.stockout_rate_pct?.toFixed(1) ?? "-"}%.
        </div>
      )}
      <div className="journal-copy">
        {journal?.trim() ? journal : "Start a run to watch the CEO reason through each weekly inbox."}
      </div>
    </aside>
  );
}

