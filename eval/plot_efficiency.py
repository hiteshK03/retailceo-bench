"""EBITDA-per-dollar bar chart — the cost-efficiency view.

Ranks LLMs by profit generated (weighted EBITDA margin points) per USD of API
spend per episode. Reads the committed frontier result JSONs.

    python -m eval.plot_efficiency --out assets/ebitda_per_dollar.png

matplotlib is an optional dependency (the [viz] extra).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from typing import Dict, List, Optional, Tuple

from .stats import weighted_score

# (label, result-file, provider)
MODELS: List[Tuple[str, str, str]] = [
    ("Claude Opus 4.6", "results/opus4_full.json", "Claude"),
    ("Claude Sonnet 4.6", "results/sonnet4_full.json", "Claude"),
    ("Qwen3.7 Max", "results/qwen37max_full.json", "Qwen"),
    ("Qwen3.7 Plus", "results/qwen37plus_full.json", "Qwen"),
]

# Validated colorblind-safe categorical hues (dataviz palette slots 1 & 2).
PROVIDER_COLOR = {"Claude": "#2a78d6", "Qwen": "#eb6834"}

_MATPLOTLIB_HINT = (
    "matplotlib is required for plotting but is not installed.\n"
    "Install it with:  pip install 'retailceo-bench[viz]'"
)

_DIFF_RE = re.compile(r"\((easy|medium|hard)\)")


def _efficiency(path: str) -> Tuple[float, float, float]:
    """Return (weighted_ebitda_margin_pct, mean_cost_per_episode, ebitda_per_dollar)."""
    with open(path) as f:
        data = json.load(f)
    per_diff: Dict[str, float] = {}
    costs: List[float] = []
    for label, entries in data.items():
        m = _DIFF_RE.search(label)
        if not m:
            continue
        per_diff[m.group(1)] = statistics.mean(e["ebitda_margin_pct"] for e in entries)
        costs += [e["est_cost_usd"] for e in entries if e.get("est_cost_usd") is not None]
    if not costs:
        raise ValueError(f"{path} has no est_cost_usd — cannot compute efficiency")
    ebitda = weighted_score(per_diff)
    cost = statistics.mean(costs)
    return ebitda, cost, ebitda / cost


def render(out_path: str, models=MODELS) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(_MATPLOTLIB_HINT) from exc

    rows = [(label, prov, *_efficiency(path)) for label, path, prov in models]
    rows.sort(key=lambda r: r[4])  # ascending efficiency -> best at top of hbar

    labels = [r[0] for r in rows]
    effs = [r[4] for r in rows]
    colors = [PROVIDER_COLOR[r[1]] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 4.6))
    y = list(range(len(rows)))
    ax.barh(y, effs, color=colors, height=0.62, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10, color="#0b0b0b")

    # Value labels at the bar ends: efficiency + the (EBITDA% @ $/ep) it comes from.
    for yi, (label, prov, ebitda, cost, eff) in zip(y, rows):
        ax.annotate(f"{eff:.1f}   ({ebitda:+.2f}% @ ${cost:.2f})",
                    (eff, yi), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=9, color="#52514e")

    ax.set_xlabel("EBITDA margin points per $ / episode  (higher = more profit per dollar)",
                  fontsize=10.5, color="#52514e")
    ax.set_title("Cost-efficiency — profit generated per dollar of API spend",
                 fontsize=13, color="#0b0b0b")
    ax.margins(x=0.22)
    ax.grid(True, axis="x", alpha=0.25, zorder=0)

    # Provider legend via proxy handles.
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=PROVIDER_COLOR[p], label=p) for p in ("Claude", "Qwen")],
              title="Provider", frameon=False, loc="lower right")

    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c3c2b7")

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Render EBITDA-per-dollar bar chart")
    p.add_argument("--out", default="assets/ebitda_per_dollar.png")
    args = p.parse_args(argv)
    try:
        out = render(args.out)
    except RuntimeError as e:
        print(str(e))
        return 3
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
