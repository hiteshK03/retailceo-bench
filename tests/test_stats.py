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


def test_weighted_score_1_2_3():
    from eval.stats import weighted_score
    # (1*1.0 + 2*2.0 + 3*3.0) / 6 = 14/6
    assert abs(weighted_score({"easy": 1.0, "medium": 2.0, "hard": 3.0}) - 14 / 6) < 1e-9


def test_weighted_score_all_equal_is_that_value():
    from eval.stats import weighted_score
    assert abs(weighted_score({"easy": 0.5, "medium": 0.5, "hard": 0.5}) - 0.5) < 1e-9


def test_weighted_score_missing_difficulty_uses_present_weights():
    from eval.stats import weighted_score
    # only medium+hard present -> (2*1.0 + 3*2.0) / (2+3) = 8/5
    assert abs(weighted_score({"medium": 1.0, "hard": 2.0}) - 8 / 5) < 1e-9


def test_weighted_score_empty_is_zero():
    from eval.stats import weighted_score
    assert weighted_score({}) == 0.0
