"""Cost-vs-score scatter: weighted benchmark score against $/episode per model.

Reads the committed frontier result JSONs and renders a PNG showing the
cost/performance tradeoff — upper-left (high score, low cost) is best value.

    python -m eval.plot_cost_score --out assets/cost_vs_score.png

matplotlib is an optional dependency (the [viz] extra).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from typing import Dict, List, Optional, Tuple

from .stats import weighted_score

# (label, result-file, provider) — provider drives color/identity.
MODELS: List[Tuple[str, str, str]] = [
    ("Claude Opus 4.6", "results/opus4_full.json", "Claude"),
    ("Claude Sonnet 4.6", "results/sonnet4_full.json", "Claude"),
    ("Qwen3.7 Plus", "results/qwen37plus_full.json", "Qwen"),
    ("Qwen3.7 Max", "results/qwen37max_full.json", "Qwen"),
]

# Validated colorblind-safe categorical hues (see dataviz palette, slots 1 & 2).
PROVIDER_COLOR = {"Claude": "#2a78d6", "Qwen": "#eb6834"}

_MATPLOTLIB_HINT = (
    "matplotlib is required for plotting but is not installed.\n"
    "Install it with:  pip install 'retailceo-bench[viz]'"
)

_DIFF_RE = re.compile(r"\((easy|medium|hard)\)")


def _model_point(path: str) -> Tuple[float, float]:
    """Return (weighted_score, mean_cost_per_episode) for one result file."""
    with open(path) as f:
        data = json.load(f)
    per_diff: Dict[str, float] = {}
    costs: List[float] = []
    for label, entries in data.items():
        m = _DIFF_RE.search(label)
        if not m:
            continue
        per_diff[m.group(1)] = statistics.mean(e["total_reward"] for e in entries)
        costs += [e["est_cost_usd"] for e in entries if e.get("est_cost_usd") is not None]
    if not costs:
        raise ValueError(f"{path} has no est_cost_usd — cannot place it on the cost axis")
    return weighted_score(per_diff), statistics.mean(costs)


def render(out_path: str, models=MODELS) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(_MATPLOTLIB_HINT) from exc

    points = [(label, prov, *_model_point(path)) for label, path, prov in models]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.set_xscale("log")

    seen = set()
    for label, prov, score, cost in points:
        color = PROVIDER_COLOR[prov]
        legend = prov if prov not in seen else None
        seen.add(prov)
        ax.scatter(cost, score, s=140, color=color, zorder=3,
                   edgecolor="#fcfcfb", linewidth=1.5, label=legend)
        # Direct label per point (secondary encoding — identity never color-alone).
        ax.annotate(label, (cost, score), textcoords="offset points",
                    xytext=(10, 6), fontsize=9, color="#0b0b0b")

    ax.set_xlabel("Cost per episode (USD, log scale)", fontsize=11, color="#52514e")
    ax.set_ylabel("Weighted benchmark score", fontsize=11, color="#52514e")
    ax.set_title("Cost vs. score — value is up and to the left", fontsize=13, color="#0b0b0b")
    ax.grid(True, which="both", alpha=0.25, zorder=0)
    ax.legend(title="Provider", frameon=False, loc="upper left")
    # Extra right headroom so the longest direct label doesn't clip the frame.
    ax.margins(y=0.18)
    xmin, xmax = ax.get_xlim()
    ax.set_xlim(xmin, xmax * 3.2)

    # Recessive spines.
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c3c2b7")

    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Render cost-vs-score scatter")
    p.add_argument("--out", default="assets/cost_vs_score.png")
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
