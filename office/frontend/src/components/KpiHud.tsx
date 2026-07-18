import type { WeekPayload } from "../types";
import { formatInr, formatNumber } from "../lib/format";

type Props = {
  week?: WeekPayload;
  maxWeeks?: number;
  status: string;
};

export function KpiHud({ week, status }: Props) {
  const kpi = week?.kpi ?? {};
  const decisionKpi = week?.decision_kpi;
  return (
    <section className="kpi-hud panel pixel-border">
      <div className="hud-topline">
        <span>Decision Snapshot</span>
        <span className={`run-status ${status}`}>{status}</span>
      </div>
      <div className="snapshot-note">
        {week?.decisions
          ? "What the CEO saw at decision time. Headline live KPIs are in the top bar."
          : "Decision-time snapshot before this week's actions close."}
      </div>
      <div className="hud-grid">
        <Metric label="CEO saw cash" value={formatInr(decisionKpi?.cash_inr ?? kpi.cash_inr)} tone="cash" />
        <Metric label="CEO saw NPS" value={formatNumber(decisionKpi?.nps, 1)} tone="info" />
        <Metric label="CEO saw stockout" value={`${formatNumber(decisionKpi?.stockout_rate_pct, 1)}%`} tone="bad" />
        <Metric label="Gross margin" value={`${formatNumber(kpi.gross_margin_pct, 1)}%`} tone="good" />
        <Metric label="SLA hit rate" value={`${formatNumber(kpi.delivery_sla_hit_rate_pct, 1)}%`} tone="info" />
        <Metric label="Crises" value={(week?.active_crises ?? []).join(", ") || "none"} tone="warn" />
      </div>
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

