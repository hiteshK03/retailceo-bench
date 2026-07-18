import type { WeekPayload } from "../types";
import { formatInr, formatNumber } from "../lib/format";

type Props = {
  week?: WeekPayload;
  maxWeeks?: number;
  status: string;
  cumulativeReward?: number;
};

type DeltaSpec = {
  value?: number;
  formatted: string;
  higherIsBetter: boolean;
  suffix?: string;
};

const EPSILON = 1e-9;

export function TopKpiBar({ week, maxWeeks = 12, status, cumulativeReward = 0 }: Props) {
  const kpi = week?.kpi ?? {};
  const pnl = week?.pnl_qtd ?? {};
  const ebitda = pnl.ebitda_qtd_inr;
  const cash = kpi.cash_inr ?? week?.cash_inr;

  const weekSub = week?.day_of_quarter
    ? `Day ${week.day_of_quarter} of quarter`
    : status === "idle"
      ? "Awaiting run"
      : "Live operations";

  return (
    <section className="top-kpi-bar pixel-border">
      <div className="kpi-week">
        <span className="kpi-week-label">Week</span>
        <span className="kpi-week-value">
          {week?.week ?? "-"}
          <span className="kpi-week-of"> / {maxWeeks}</span>
        </span>
        <span className="kpi-week-sub">{weekSub}</span>
      </div>
      <div className="top-kpi-stats">
        <StatCell
          label="EBITDA (QTD)"
          value={formatInr(ebitda)}
          tone={typeof ebitda === "number" && ebitda < 0 ? "bad" : "good"}
          sub={`${formatNumber(pnl.ebitda_margin_pct, 1)}% margin`}
        />
        <StatCell
          label="Revenue (QTD)"
          value={formatInr(pnl.revenue_qtd_inr)}
          tone="info"
          delta={{
            value: kpi.revenue_delta_pct,
            formatted: `${Math.abs(kpi.revenue_delta_pct ?? 0).toFixed(1)}%`,
            higherIsBetter: true,
            suffix: "WoW",
          }}
        />
        <StatCell
          label="Cash"
          value={formatInr(cash)}
          tone="cash"
          delta={{
            value: kpi.cash_delta_inr,
            formatted: formatInr(Math.abs(kpi.cash_delta_inr ?? 0)),
            higherIsBetter: true,
          }}
        />
        <StatCell
          label="Stock-out"
          value={`${formatNumber(kpi.stockout_rate_pct, 1)}%`}
          tone="bad"
          delta={{
            value: kpi.stockout_delta_pts,
            formatted: `${Math.abs(kpi.stockout_delta_pts ?? 0).toFixed(1)} pt`,
            higherIsBetter: false,
          }}
        />
        <StatCell
          label="NPS"
          value={formatNumber(kpi.nps, 1)}
          tone="info"
          delta={{
            value: kpi.nps_delta,
            formatted: `${Math.abs(kpi.nps_delta ?? 0).toFixed(1)}`,
            higherIsBetter: true,
          }}
        />
        <StatCell
          label="Reward (wk)"
          value={formatNumber(week?.reward, 3)}
          tone="reward"
          sub={`cumulative ${formatNumber(cumulativeReward, 3)}`}
        />
      </div>
    </section>
  );
}

function StatCell({
  label,
  value,
  tone,
  sub,
  delta,
}: {
  label: string;
  value: string;
  tone: string;
  sub?: string;
  delta?: DeltaSpec;
}) {
  return (
    <div className={`top-kpi-cell ${tone}`}>
      <span className="cell-label">{label}</span>
      <span className="cell-value">{value}</span>
      {delta ? (
        <DeltaTag {...delta} />
      ) : (
        <span className="cell-sub">{sub ?? "\u00a0"}</span>
      )}
    </div>
  );
}

function DeltaTag({ value, formatted, higherIsBetter, suffix }: DeltaSpec) {
  if (value === undefined || value === null || Number.isNaN(value) || Math.abs(value) < EPSILON) {
    return <span className="cell-delta flat">no change</span>;
  }
  const improved = higherIsBetter ? value > 0 : value < 0;
  const arrow = value > 0 ? "\u25b2" : "\u25bc";
  return (
    <span className={`cell-delta ${improved ? "up" : "down"}`}>
      {arrow} {formatted}
      {suffix ? ` ${suffix}` : ""}
    </span>
  );
}
