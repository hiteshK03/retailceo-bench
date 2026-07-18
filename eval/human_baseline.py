"""Aggregate human playthrough recordings into a difficulty-grouped baseline."""

from __future__ import annotations

import glob
import json
import os
import statistics
from typing import Any, Dict, List

from . import stats as _stats


def _load_rewards_by_difficulty(results_dir: str) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        meta = d.get("meta", {})
        diff = meta.get("difficulty")
        reward = meta.get("total_reward")
        if diff is None or reward is None:
            continue
        out.setdefault(diff, []).append(float(reward))
    return out


def aggregate(results_dir: str = "results/human") -> Dict[str, Any]:
    grouped = _load_rewards_by_difficulty(results_dir)
    agg: Dict[str, Any] = {}
    for diff, rewards in grouped.items():
        mean, lo, hi = _stats.bootstrap_ci_mean(rewards)
        sd = statistics.stdev(rewards) if len(rewards) > 1 else 0.0
        stderr = sd / (len(rewards) ** 0.5) if rewards else 0.0
        agg[diff] = {"n": len(rewards), "mean": mean, "stderr": stderr,
                     "ci_lo": lo, "ci_hi": hi}
    return agg


def write_baseline(agg: Dict[str, Any], out: str = "results/human_baseline.json") -> str:
    with open(out, "w") as f:
        json.dump(agg, f, indent=2)
    return out
