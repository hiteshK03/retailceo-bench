"""Trace visualization for RetailCEO-Bench.

Reads a trace JSON written by `python -m eval.cli trace ...` and renders a
multi-panel figure of KPI trajectories, weekly reward, and EBITDA over the
episode weeks. Saves a PNG.

matplotlib is an optional dependency (install with the [viz] extra). If it is
missing this module raises a clear, actionable error instead of a bare
ImportError.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

CRORE = 1e7  # 1 Cr = 10^7 INR

_MATPLOTLIB_HINT = (
    "matplotlib is required for trace plotting but is not installed.\n"
    "Install it with:  pip install 'retailceo-bench[viz]'   "
    "(or:  pip install matplotlib)"
)


def _require_matplotlib():
    """Import matplotlib lazily with a friendly error if it is missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless / no display required
        import matplotlib.pyplot as plt
        return plt
    except ImportError as exc:  # pragma: no cover - env dependent
        raise RuntimeError(_MATPLOTLIB_HINT) from exc


def load_trace(path: str) -> Dict[str, Any]:
    """Load and validate a trace JSON payload."""
    with open(path) as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "trace" not in payload:
        raise ValueError(
            f"{path} does not look like a trace file "
            "(expected top-level {'meta':..., 'trace':[...]})."
        )
    if not payload["trace"]:
        raise ValueError(f"{path} contains an empty trace (no weekly steps).")
    return payload


def _series(trace: List[Dict[str, Any]], group: str, field: str,
            scale: float = 1.0) -> List[float]:
    """Extract a numeric series from each weekly step.

    group == "" reads a top-level entry key (e.g. 'reward'); otherwise reads
    entry[group][field] (e.g. kpi.revenue_inr, pnl_qtd.ebitda_qtd_inr).
    Missing values default to 0.0 so partial traces still plot.
    """
    out: List[float] = []
    for step in trace:
        if group:
            val = (step.get(group) or {}).get(field, 0.0)
        else:
            val = step.get(field, 0.0)
        out.append((val or 0.0) * scale)
    return out


def plot_trace(payload: Dict[str, Any], out_path: str,
               title: Optional[str] = None) -> str:
    """Render the multi-panel trace figure and save it to out_path (PNG)."""
    plt = _require_matplotlib()

    trace = payload["trace"]
    meta = payload.get("meta", {})
    weeks = [step.get("week", i + 1) for i, step in enumerate(trace)]

    panels = [
        ("Revenue (Rs Cr)", _series(trace, "kpi", "revenue_inr", 1.0 / CRORE),
         "Rs Cr"),
        ("Gross Margin (%)", _series(trace, "kpi", "gross_margin_pct"), "%"),
        ("NPS", _series(trace, "kpi", "nps"), ""),
        ("Stockout Rate (%)", _series(trace, "kpi", "stockout_rate_pct"), "%"),
        ("Cash (Rs Cr)", _series(trace, "kpi", "cash_inr", 1.0 / CRORE), "Rs Cr"),
        ("EBITDA QTD (Rs Cr)",
         _series(trace, "pnl_qtd", "ebitda_qtd_inr", 1.0 / CRORE), "Rs Cr"),
        ("Weekly Reward", _series(trace, "", "reward"), ""),
    ]

    n = len(panels)
    ncols = 2
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 3.0 * nrows),
                             squeeze=False)
    flat = [ax for row in axes for ax in row]

    crisis_weeks = {
        step.get("week", i + 1)
        for i, step in enumerate(trace)
        if step.get("active_crises")
    }

    for ax, (label, ys, unit) in zip(flat, panels):
        ax.plot(weeks, ys, marker="o", markersize=4, linewidth=1.8,
                color="#1f77b4")
        ax.set_title(label, fontsize=11)
        ax.set_xlabel("Week")
        if unit:
            ax.set_ylabel(unit)
        ax.grid(True, alpha=0.3)
        if label.startswith(("Weekly Reward", "EBITDA", "Cash")):
            ax.axhline(0.0, color="#888", linewidth=0.8, linestyle="--")
        for cw in crisis_weeks:
            ax.axvspan(cw - 0.5, cw + 0.5, color="#d62728", alpha=0.08)

    for ax in flat[n:]:
        ax.axis("off")

    if title is None:
        title = (
            f"RetailCEO trace - {meta.get('policy', '?')} "
            f"(seed {meta.get('seed', '?')}, "
            f"total reward {meta.get('total_reward', float('nan')):+.2f})"
        )
    fig.suptitle(title, fontsize=13, y=1.00)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_trace_file(in_path: str, out_path: Optional[str] = None,
                    title: Optional[str] = None) -> str:
    """Convenience: load a trace file and render it.

    out_path defaults to the input path with a .png suffix.
    """
    payload = load_trace(in_path)
    if out_path is None:
        base, _ = os.path.splitext(in_path)
        out_path = base + ".png"
    return plot_trace(payload, out_path, title=title)
