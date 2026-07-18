from eval import stats


def test_bootstrap_ci_determinism_and_bracketing():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    r1 = stats.bootstrap_ci_mean(data, n_resamples=2000, seed=7)
    r2 = stats.bootstrap_ci_mean(data, n_resamples=2000, seed=7)
    assert r1 == r2                      # deterministic
    mean, lo, hi = r1
    assert abs(mean - 3.0) < 1e-9
    assert lo <= mean <= hi


def test_bootstrap_ci_small_n_collapses():
    assert stats.bootstrap_ci_mean([2.5], seed=1) == (2.5, 2.5, 2.5)
    assert stats.bootstrap_ci_mean([], seed=1) == (0.0, 0.0, 0.0)


def test_paired_bootstrap_detects_and_rejects():
    a = [10.0, 11.0, 12.0, 13.0, 14.0]
    b = [1.0, 2.0, 3.0, 4.0, 5.0]
    d, lo, hi, p, n = stats.paired_bootstrap_diff(a, b, n_resamples=5000, seed=1)
    assert n == 5 and abs(d - 9.0) < 1e-9 and p < 0.05  # clear separation
    d2, lo2, hi2, p2, _ = stats.paired_bootstrap_diff(a, a, n_resamples=5000, seed=1)
    assert d2 == 0.0 and p2 == 1.0                       # identical => not sig
    assert lo <= d <= hi


def test_sig_stars():
    assert stats.sig_stars(0.0005) == "***"
    assert stats.sig_stars(0.005) == "**"
    assert stats.sig_stars(0.02) == "*"
    assert stats.sig_stars(0.5) == "ns"
