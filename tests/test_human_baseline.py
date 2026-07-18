import json

from eval import human_baseline


def _rec(tmp_path, diff, seed, reward, handle="p"):
    p = tmp_path / f"{diff}_seed{seed}_{handle}_{seed}.json"
    p.write_text(json.dumps({
        "meta": {"mode": "human", "player_handle": handle, "seed": seed,
                 "difficulty": diff, "total_reward": reward},
        "trace": [], "summary": {"total_reward": reward},
    }))
    return p


def test_aggregate_groups_by_difficulty(tmp_path):
    _rec(tmp_path, "medium", 42, 1.0)
    _rec(tmp_path, "medium", 43, 2.0)
    _rec(tmp_path, "hard", 42, 0.0)
    agg = human_baseline.aggregate(results_dir=str(tmp_path))
    assert agg["medium"]["n"] == 2
    assert abs(agg["medium"]["mean"] - 1.5) < 1e-9
    assert "ci_lo" in agg["medium"] and "ci_hi" in agg["medium"]
    assert agg["hard"]["n"] == 1


def test_aggregate_empty_dir(tmp_path):
    assert human_baseline.aggregate(results_dir=str(tmp_path)) == {}
