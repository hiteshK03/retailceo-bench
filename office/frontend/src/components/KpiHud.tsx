import type { WeekPayload } from "../types";
import { formatInr, formatNumber } from "../lib/format";

type Props = {
  week?: WeekPayload;
  maxWeeks?: number;
  status: string;
};

export function KpiHud({ week, maxWeeks = 12, status }: Props) {
  const kpi = week?.kpi ?? {};
  const pnl = week?.pnl_qtd ?? {};
  const decisionKpi = week?.decision_kpi;
  return (
    <section className="kpi-hud panel pixel-border">
      <div className="hud-topline">
        <span>Week {week?.week ?? "-"}/{maxWeeks}</span>
        <span className={`run-status ${status}`}>{status}</span>
      </div>
      <div className="snapshot-note">
        {week?.decisions
          ? "Post-close KPIs; CEO saw the decision snapshot."
          : "Decision-time snapshot before this week's actions close."}
      </div>
      <div className="hud-grid">
        <Metric label="EBITDA" value={`${formatNumber(pnl.ebitda_margin_pct, 2)}%`} tone="good" />
        <Metric label="Stockout" value={`${formatNumber(kpi.stockout_rate_pct, 1)}%`} tone="bad" />
        <Metric label="NPS" value={formatNumber(kpi.nps, 1)} tone="info" />
        <Metric label="Cash close" value={formatInr(kpi.cash_inr ?? week?.cash_inr)} tone="cash" />
        <Metric label="CEO saw cash" value={formatInr(decisionKpi?.cash_inr ?? kpi.cash_inr)} tone="cash" />
        <Metric label="Reward" value={formatNumber(week?.reward, 3)} tone="reward" />
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

