"""Small-n statistical helpers for policy comparison (stdlib only).

Percentile bootstrap CI for a mean, and a paired bootstrap
difference-of-means test (CI + two-sided p-value). Seeded RNG so all
output is deterministic across runs (independent of PYTHONHASHSEED).

Pure stdlib on purpose: the core package depends only on pydantic, and the
benchmark must stay `pip install`-able without numpy/scipy.
"""
from __future__ import annotations

import random
import statistics
from typing import List, Sequence, Tuple

DEFAULT_SEED = 12345
DEFAULT_RESAMPLES = 10000


def bootstrap_ci_mean(
    data: Sequence[float],
    n_resamples: int = DEFAULT_RESAMPLES,
    ci: float = 0.95,
    seed: int = DEFAULT_SEED,
) -> Tuple[float, float, float]:
    """Percentile bootstrap CI for the mean.

    Returns (mean, lo, hi). For n < 2 the CI collapses to the point value.
    """
    n = len(data)
    mean = statistics.mean(data) if n else 0.0
    if n < 2:
        return (mean, mean, mean)
    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(n_resamples):
        total = 0.0
        for _ in range(n):
            total += data[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    alpha = (1.0 - ci) / 2.0
    lo = means[int(alpha * n_resamples)]
    hi = means[min(n_resamples - 1, int((1.0 - alpha) * n_resamples))]
    return (mean, lo, hi)


def paired_bootstrap_diff(
    a: Sequence[float],
    b: Sequence[float],
    n_resamples: int = DEFAULT_RESAMPLES,
    ci: float = 0.95,
    seed: int = DEFAULT_SEED,
) -> Tuple[float, float, float, float, int]:
    """Paired bootstrap on the per-seed differences d_i = a_i - b_i.

    ``a`` and ``b`` MUST be aligned (same seed order). Returns
    (mean_diff, ci_lo, ci_hi, p_value, n_pairs) where:
      - mean_diff = mean(a - b)  (positive => a beats b)
      - [ci_lo, ci_hi] = percentile bootstrap CI of the mean difference
      - p_value = two-sided bootstrap hypothesis test of H0: mean_diff == 0,
        computed by re-centering the diffs to mean 0, resampling with
        replacement, and measuring the tail |boot_mean| >= |obs|.

    Paired (not two-sample) because every policy runs on the identical seed
    set — the seed is the dominant variance source, so pairing removes it and
    is far more powerful at n=5-10.
    """
    diffs = [x - y for x, y in zip(a, b)]
    n = len(diffs)
    if n == 0:
        return (0.0, 0.0, 0.0, 1.0, 0)
    obs = statistics.mean(diffs)
    if n < 2:
        return (obs, obs, obs, 1.0, n)
    rng = random.Random(seed)

    # (1) CI: percentile bootstrap of the mean difference.
    boot_means: List[float] = []
    for _ in range(n_resamples):
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        boot_means.append(total / n)
    boot_means.sort()
    alpha = (1.0 - ci) / 2.0
    lo = boot_means[int(alpha * n_resamples)]
    hi = boot_means[min(n_resamples - 1, int((1.0 - alpha) * n_resamples))]

    # (2) two-sided p-value: null-center the diffs, resample, count tail.
    centered = [d - obs for d in diffs]
    abs_obs = abs(obs)
    count = 1  # +1: observed sample is a valid draw under H0 (avoids p=0)
    for _ in range(n_resamples):
        total = 0.0
        for _ in range(n):
            total += centered[rng.randrange(n)]
        if abs(total / n) >= abs_obs - 1e-12:
            count += 1
    p = count / (n_resamples + 1)
    return (obs, lo, hi, p, n)


def sig_stars(p: float) -> str:
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"
