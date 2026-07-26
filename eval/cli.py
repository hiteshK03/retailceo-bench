"""CLI entry point for RetailCEO-Bench evaluation.

Usage:
    python -m eval.cli baselines --seeds 42 43 44 --difficulty medium --weeks 12
    python -m eval.cli frontier --model claude-sonnet-4-6 --seeds 42 43
    python -m eval.cli trace --policy heuristic --seed 42 --out trace.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List

from retailceo.models import BenchmarkConfig
from .policies import (
    CEOPolicy,
    RandomCEO,
    AllApproveCEO,
    HeuristicCEO,
    OracleCEO,
)
from .runner import EpisodeResult, run_one_episode, run_policy, summarise
from . import stats as _stats

PROTOCOLS = {
    "lite": {
        "seeds": list(range(42, 47)),       # 42–46, 5 seeds
        "difficulties": ["medium"],
        "weeks": 12,
    },
    "full": {
        "seeds": list(range(42, 52)),       # 42–51, 10 seeds
        "difficulties": ["easy", "medium", "hard"],
        "weeks": 12,
    },
}


def _parse_extra_headers() -> Dict[str, str]:
    raw = os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "")
    if not raw:
        return {}
    headers: Dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            k, v = pair.split(":", 1)
            headers[k.strip()] = v.strip()
    return headers


def _make_config(args) -> BenchmarkConfig:
    years = getattr(args, "years", 0) or 0
    return BenchmarkConfig(
        weeks_per_quarter=args.weeks,
        horizon_years=years,
        difficulty=args.difficulty,
        crisis_prob=args.crisis_prob,
        starting_cash_inr=args.starting_cash,
    )


def cmd_baselines(args) -> int:
    protocol = PROTOCOLS.get(args.protocol) if args.protocol else None

    all_policies = {
        "random": RandomCEO(seed=0),
        "all_approve": AllApproveCEO(),
        "heuristic": HeuristicCEO(),
        "oracle": OracleCEO(),
    }
    selected = args.policies or list(all_policies.keys())
    policies: List[CEOPolicy] = [all_policies[p] for p in selected]

    if protocol:
        seeds = args.seeds or protocol["seeds"]
        difficulties = protocol["difficulties"]
        weeks = protocol["weeks"]
        print(f"[protocol: {args.protocol}] {len(seeds)} seeds × "
              f"{len(difficulties)} difficulties × {weeks} weeks")
    else:
        seeds = args.seeds or list(range(1, 6))
        difficulties = [args.difficulty]
        weeks = args.weeks

    results_by_policy: Dict[str, List[EpisodeResult]] = {}
    for p in policies:
        for diff in difficulties:
            config = BenchmarkConfig(
                weeks_per_quarter=weeks,
                horizon_years=getattr(args, "years", 0) or 0,
                difficulty=diff,
                crisis_prob=args.crisis_prob,
                starting_cash_inr=args.starting_cash,
            )
            label = f"{p.name} ({diff})" if len(difficulties) > 1 else p.name
            results_by_policy.setdefault(label, []).extend(
                run_policy(
                    p, seeds, config=config, verbose=args.verbose, quiet=args.quiet,
                )
            )

    summarise(results_by_policy)

    if args.out:
        payload = {
            name: [
                {
                    "seed": r.seed,
                    "difficulty": r.difficulty,
                    "total_reward": r.total_reward,
                    "ebitda_margin_pct": r.ebitda_margin_pct,
                    "avg_stockout_pct": r.avg_stockout_pct,
                    "avg_nps": r.avg_nps,
                    "starting_cash_inr": r.starting_cash_inr,
                    "final_cash_inr": r.final_cash_inr,
                    "min_cash_inr": r.min_cash_inr,
                    "free_cash_flow_inr": r.free_cash_flow_inr,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "est_cost_usd": r.est_cost_usd,
                }
                for r in res
            ]
            for name, res in results_by_policy.items()
        }
        with open(args.out, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\nResults saved to {args.out}")

    return 0


def cmd_frontier(args) -> int:
    from .frontier import FrontierCEO

    protocol = PROTOCOLS.get(args.protocol) if args.protocol else None

    policy = FrontierCEO(
        model=args.model,
        provider=args.provider,
        api_base=args.api_base,
        extra_headers=_parse_extra_headers() or None,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        parse_retries=args.parse_retries,
        dual_head=args.dual_head,
        permissive=args.permissive,
    )

    if protocol:
        seeds = args.seeds or protocol["seeds"]
        difficulties = protocol["difficulties"]
        weeks = protocol["weeks"]
        print(f"[protocol: {args.protocol}] {len(seeds)} seeds × "
              f"{len(difficulties)} difficulties × {weeks} weeks")
    else:
        seeds = args.seeds or list(range(1, 4))
        difficulties = [args.difficulty]
        weeks = args.weeks

    all_results: Dict[str, List[EpisodeResult]] = {}
    for diff in difficulties:
        config = BenchmarkConfig(
            weeks_per_quarter=weeks,
            horizon_years=getattr(args, "years", 0) or 0,
            difficulty=diff,
            crisis_prob=args.crisis_prob,
            starting_cash_inr=args.starting_cash,
        )
        label = f"{policy.name} ({diff})" if len(difficulties) > 1 else policy.name
        results = run_policy(
            policy, seeds, config=config, verbose=args.verbose, quiet=args.quiet,
        )
        all_results[label] = results

    summarise(all_results)

    if args.out:
        payload = {
            name: [
                {
                    "seed": r.seed,
                    "difficulty": r.difficulty,
                    "total_reward": r.total_reward,
                    "ebitda_margin_pct": r.ebitda_margin_pct,
                    "avg_stockout_pct": r.avg_stockout_pct,
                    "avg_nps": r.avg_nps,
                    "starting_cash_inr": r.starting_cash_inr,
                    "final_cash_inr": r.final_cash_inr,
                    "min_cash_inr": r.min_cash_inr,
                    "free_cash_flow_inr": r.free_cash_flow_inr,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "est_cost_usd": r.est_cost_usd,
                }
                for r in res
            ]
            for name, res in all_results.items()
        }
        with open(args.out, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\nResults saved to {args.out}")

    return 0


def cmd_trace(args) -> int:
    config = _make_config(args)
    seed = args.seed or 42

    policy_map = {
        "random": lambda: RandomCEO(seed=0),
        "all_approve": lambda: AllApproveCEO(),
        "heuristic": lambda: HeuristicCEO(),
        "oracle": lambda: OracleCEO(),
    }

    if args.policy == "frontier":
        from .frontier import FrontierCEO
        policy = FrontierCEO(
            model=args.model,
            provider=args.provider,
            api_base=args.api_base,
            extra_headers=_parse_extra_headers() or None,
            temperature=args.temperature,
            parse_retries=getattr(args, "parse_retries", 0),
        )
    elif args.policy in policy_map:
        policy = policy_map[args.policy]()
    else:
        print(f"Unknown policy: {args.policy}", file=sys.stderr)
        return 2

    print(f"[trace] {policy.name} seed={seed} → {args.out}")
    res = run_one_episode(
        policy, seed, config=config, collect_trace=True, verbose=args.verbose,
    )

    payload = {
        "meta": {
            "policy": res.policy,
            "seed": res.seed,
            "total_reward": res.total_reward,
            "final_cash_inr": res.final_cash_inr,
            "ebitda_qtd_inr": res.ebitda_qtd_inr,
            "ebitda_margin_pct": res.ebitda_margin_pct,
            "avg_stockout_pct": res.avg_stockout_pct,
            "avg_nps": res.avg_nps,
        },
        "trace": res.trace,
    }
    out_path = args.out or "trace.json"
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"  wrote {len(res.trace)} weekly steps to {out_path}")
    return 0


_LABEL_RE = __import__("re").compile(r"^(?P<policy>.*?)\s*\((?P<diff>easy|medium|hard)\)\s*$")


# CLI metric name -> result-JSON field. `reward` is the RL training signal;
# the default is EBITDA margin, the primary business outcome the benchmark ranks on.
_METRIC_FIELD = {
    "ebitda": "ebitda_margin_pct",
    "reward": "total_reward",
    "stockout": "avg_stockout_pct",
    "nps": "avg_nps",
}


def cmd_leaderboard(args) -> int:
    """Aggregate result JSONs into a difficulty-weighted, ranked leaderboard.

    Ranks by --metric (default: ebitda margin — the business outcome). Also
    shows the companion finance columns (stockout, NPS, min-cash). `--metric
    reward` ranks by the RL training signal instead.
    """
    import statistics as _stat
    from . import stats as _stats

    rank_field = _METRIC_FIELD.get(args.metric, args.metric)
    # policy -> difficulty -> {field: [values]}
    agg: Dict[str, Dict[str, Dict[str, List[float]]]] = {}
    fields = ["ebitda_margin_pct", "total_reward", "avg_stockout_pct", "avg_nps",
              "min_cash_inr", rank_field]
    for path in args.results:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            continue
        for label, entries in data.items():
            m = _LABEL_RE.match(label)
            if not m:
                continue
            policy = _clean_policy_name(m.group("policy"))
            diff = m.group("diff")
            slot = agg.setdefault(policy, {}).setdefault(diff, {})
            for fld in fields:
                slot.setdefault(fld, []).extend(
                    e[fld] for e in entries if e.get(fld) is not None
                )

    if not agg:
        print("[leaderboard] no difficulty-labelled results found in inputs")
        return 0

    def wmean(by_diff, fld, scale=1.0):
        means = {d: _stat.mean(v[fld]) * scale for d, v in by_diff.items() if v.get(fld)}
        return _stats.weighted_score(means)

    table = []
    for policy, by_diff in agg.items():
        rank = wmean(by_diff, rank_field)
        ebitda = wmean(by_diff, "ebitda_margin_pct")
        stockout = wmean(by_diff, "avg_stockout_pct")
        nps = wmean(by_diff, "avg_nps")
        mincash = wmean(by_diff, "min_cash_inr", scale=1e-7)
        n = max((len(v.get(rank_field, [])) for v in by_diff.values()), default=0)
        table.append((policy, rank, ebitda, stockout, nps, mincash, n))
    table.sort(key=lambda row: -row[1])

    metric_lbl = args.metric
    print(f"\n=== Leaderboard (weighted {args.weights}, ranked by {metric_lbl}, "
          f"{len(table)} policies) ===")
    hdr = (f"{'policy':<24} {'EBITDA%':>8} {'stockout%':>9} {'NPS':>6} "
           f"{'minCash':>8} {'n':>4}")
    print(hdr)
    print("-" * len(hdr))
    for policy, rank, ebitda, stockout, nps, mincash, n in table:
        print(f"{policy:<24} {ebitda:+8.2f} {stockout:9.1f} {nps:6.1f} "
              f"{mincash:+8.1f} {n:>4}")
    print(f"\n  weighted = (1*easy + 2*medium + 3*hard) / 6. Ranked by {metric_lbl}; "
          "EBITDA margin higher = better.")
    return 0


def _clean_policy_name(raw: str) -> str:
    """Normalise a result label's policy component for display.

    'frontier:Claude-Opus-4-permissive' -> 'Claude-Opus-4', bare names as-is.
    """
    name = raw.strip()
    if name.startswith("frontier:"):
        name = name[len("frontier:"):]
    for suffix in ("-permissive", "-dual"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def cmd_plot(args) -> int:
    from .visualize import plot_trace_file
    try:
        out = plot_trace_file(args.trace, out_path=args.out, title=args.title)
    except RuntimeError as e:            # matplotlib missing -> friendly msg
        print(str(e), file=sys.stderr)
        return 3
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[plot] error: {e}", file=sys.stderr)
        return 2
    print(f"[plot] wrote figure to {out}")
    return 0


def cmd_human_baseline(args) -> int:
    from .human_baseline import aggregate, write_baseline
    agg = aggregate(results_dir=args.dir)
    if not agg:
        print(f"[human-baseline] no recordings found in {args.dir}")
        return 0
    print(f"\n=== Human baseline ({args.dir}) ===")
    print(f"{'difficulty':<10} {'n':>4} {'mean':>9}  95% CI")
    print("-" * 44)
    for diff in ("easy", "medium", "hard"):
        if diff in agg:
            a = agg[diff]
            print(f"{diff:<10} {a['n']:>4} {a['mean']:+9.3f}  "
                  f"[{a['ci_lo']:+.3f}, {a['ci_hi']:+.3f}]")
    out = write_baseline(agg, out=args.out)
    print(f"\nWrote {out}")
    return 0


def _print_stats(
    all_results: Dict[str, List[EpisodeResult]],
    baseline: str | None,
    resamples: int,
    ci: float,
    seed: int,
) -> None:
    names = [n for n, res in all_results.items() if res]
    if not names:
        return
    ci_pct = int(round(ci * 100))

    # ---- Per-policy bootstrap CI table ----
    print(
        f"\n=== Per-policy reward: bootstrap {ci_pct}% CI "
        f"({resamples} resamples, seed={seed}) ==="
    )
    hdr = f"{'policy':<22} {'n':>3}  {'mean':>9}  {ci_pct}% CI"
    print(hdr)
    print("-" * max(len(hdr), 48))
    for name in names:
        rewards = [r.total_reward for r in all_results[name]]
        mean, lo, hi = _stats.bootstrap_ci_mean(
            rewards, n_resamples=resamples, ci=ci, seed=seed
        )
        print(
            f"{name:<22} {len(rewards):>3}  {mean:+9.3f}  "
            f"[{lo:+8.3f}, {hi:+8.3f}]"
        )

    # ---- Pairwise significance vs baseline ----
    if baseline is None:
        baseline = "random" if "random" in names else names[0]
    if baseline not in names:
        print(f"\n[stats] baseline '{baseline}' not found; skipping matrix.")
        return

    base_map = {r.seed: r.total_reward for r in all_results[baseline]}
    print(
        f"\n=== Pairwise vs '{baseline}': paired bootstrap "
        f"(two-sided p, {resamples} resamples, seed={seed}) ==="
    )
    hdr2 = (
        f"{'policy':<22} {'pairs':>5}  {'d_mean':>9}  "
        f"{ci_pct}% CI(d){'':<8} {'p':>8}  sig"
    )
    print(hdr2)
    print("-" * max(len(hdr2), 64))
    for name in names:
        if name == baseline:
            continue
        this_map = {r.seed: r.total_reward for r in all_results[name]}
        common = sorted(set(base_map) & set(this_map))
        if len(common) < 2:
            print(f"{name:<22} {len(common):>5}  (no shared seeds; n/a)")
            continue
        a = [this_map[s] for s in common]   # candidate
        b = [base_map[s] for s in common]   # baseline
        d, lo, hi, p, npairs = _stats.paired_bootstrap_diff(
            a, b, n_resamples=resamples, ci=ci, seed=seed
        )
        print(
            f"{name:<22} {npairs:>5}  {d:+9.3f}  "
            f"[{lo:+7.2f}, {hi:+7.2f}]   {p:8.4f}  {_stats.sig_stars(p)}"
        )
    print("\n  d_mean = mean(policy - baseline) per shared seed; "
          "positive favours the policy.  * p<.05  ** p<.01  *** p<.001")


def cmd_compare(args) -> int:
    all_results: Dict[str, List[EpisodeResult]] = {}
    for path in args.results:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            for name, entries in data.items():
                all_results.setdefault(name, []).extend(
                    EpisodeResult(
                        policy=name,
                        seed=e["seed"],
                        total_reward=e["total_reward"],
                        weekly_rewards=[],
                        starting_cash_inr=e.get("starting_cash_inr", 0),
                        final_cash_inr=e.get("final_cash_inr", 0),
                        revenue_qtd_inr=0,
                        ebitda_qtd_inr=0,
                        ebitda_margin_pct=e.get("ebitda_margin_pct", 0),
                        min_cash_inr=e.get("min_cash_inr", 0),
                        avg_stockout_pct=e.get("avg_stockout_pct", 0),
                        avg_nps=e.get("avg_nps", 0),
                        prompt_tokens=e.get("prompt_tokens"),
                        completion_tokens=e.get("completion_tokens"),
                        total_tokens=e.get("total_tokens"),
                        est_cost_usd=e.get("est_cost_usd"),
                    )
                    for e in entries
                )
        elif isinstance(data, list):
            name = path.replace(".json", "").split("/")[-1]
            all_results[name] = [
                EpisodeResult(
                    policy=name,
                    seed=e["seed"],
                    total_reward=e["total_reward"],
                    weekly_rewards=[],
                    starting_cash_inr=e.get("starting_cash_inr", 0),
                    final_cash_inr=e.get("final_cash_inr", 0),
                    revenue_qtd_inr=0,
                    ebitda_qtd_inr=0,
                    ebitda_margin_pct=e.get("ebitda_margin_pct", 0),
                    min_cash_inr=e.get("min_cash_inr", 0),
                    avg_stockout_pct=e.get("avg_stockout_pct", 0),
                    avg_nps=e.get("avg_nps", 0),
                )
                for e in data
            ]

    summarise(all_results)

    if not getattr(args, "no_stats", False):
        _print_stats(
            all_results,
            baseline=getattr(args, "baseline", None),
            resamples=getattr(args, "resamples", _stats.DEFAULT_RESAMPLES),
            ci=getattr(args, "ci", 0.95),
            seed=getattr(args, "stat_seed", _stats.DEFAULT_SEED),
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RetailCEO-Bench evaluation CLI"
    )
    parser.add_argument("--weeks", type=int, default=12)
    parser.add_argument("--years", type=int, default=0,
                        help="Multi-year horizon (1/3/5). Overrides --weeks when set.")
    parser.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
    parser.add_argument("--crisis-prob", type=float, default=0.85)
    parser.add_argument("--starting-cash", type=float, default=2e8)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--quiet", action="store_true")

    sub = parser.add_subparsers(dest="command")

    # baselines
    bp = sub.add_parser("baselines", help="Run baseline policies")
    bp.add_argument("--seeds", type=int, nargs="+", default=None)
    bp.add_argument("--policies", type=str, nargs="+", default=None,
                     help="Which policies to run (default: all)",
                     choices=["random", "all_approve", "heuristic", "oracle"])
    bp.add_argument("--protocol", default=None, choices=["lite", "full"],
                     help="Standardized eval protocol (overrides --seeds/--difficulty)")
    bp.add_argument("--out", type=str, default=None)

    # frontier
    fp = sub.add_parser("frontier", help="Run frontier model")
    fp.add_argument("--model", type=str, default=None)
    fp.add_argument("--provider", default="auto", choices=["auto", "anthropic", "openai"])
    fp.add_argument("--api-base", type=str, default=None)
    fp.add_argument("--temperature", type=float, default=0.0)
    fp.add_argument("--max-tokens", type=int, default=4096)
    fp.add_argument("--parse-retries", type=int, default=0,
                     help="Re-prompt attempts on unparseable output. "
                          "Default 0 = official protocol (no retries; fall back to "
                          "request_info). Set >0 only for exploratory runs.")
    fp.add_argument("--dual-head", action="store_true")
    fp.add_argument("--permissive", action="store_true")
    fp.add_argument("--seeds", type=int, nargs="+", default=None)
    fp.add_argument("--protocol", default=None, choices=["lite", "full"],
                     help="Standardized eval protocol (overrides --seeds/--difficulty)")
    fp.add_argument("--out", type=str, default=None)

    # trace
    tp = sub.add_parser("trace", help="Single episode trace")
    tp.add_argument("--policy", default="heuristic",
                     choices=["random", "all_approve", "heuristic", "oracle", "frontier"])
    tp.add_argument("--seed", type=int, default=None)
    tp.add_argument("--out", type=str, default="trace.json")
    tp.add_argument("--model", type=str, default=None)
    tp.add_argument("--provider", default="auto")
    tp.add_argument("--api-base", type=str, default=None)
    tp.add_argument("--temperature", type=float, default=0.0)

    # compare
    cp = sub.add_parser("compare", help="Compare result files")
    cp.add_argument("results", nargs="+", help="JSON result files to compare")
    cp.add_argument("--baseline", type=str, default=None,
                    help="Policy name to test others against "
                         "(default: 'random' if present, else first policy)")
    cp.add_argument("--resamples", type=int, default=_stats.DEFAULT_RESAMPLES,
                    help="Bootstrap resamples (default 10000)")
    cp.add_argument("--ci", type=float, default=0.95,
                    help="Confidence level for intervals (default 0.95)")
    cp.add_argument("--stat-seed", type=int, default=_stats.DEFAULT_SEED,
                    help="RNG seed for the bootstrap (reproducibility)")
    cp.add_argument("--no-stats", action="store_true",
                    help="Only print the summarise() table, skip CI/significance")

    # plot
    pp = sub.add_parser("plot", help="Render KPI/reward/EBITDA charts from a trace JSON")
    pp.add_argument("trace", help="Trace JSON file written by the 'trace' command")
    pp.add_argument("--out", type=str, default=None,
                    help="Output PNG path (default: <trace>.png)")
    pp.add_argument("--title", type=str, default=None,
                    help="Override figure title")

    # human-baseline
    hb = sub.add_parser("human-baseline", help="Aggregate results/human/*.json into a baseline")
    hb.add_argument("--dir", type=str, default="results/human")
    hb.add_argument("--out", type=str, default="results/human_baseline.json")

    # leaderboard
    lb = sub.add_parser("leaderboard",
                        help="Rank result JSONs by difficulty-weighted finance terms")
    lb.add_argument("results", nargs="+", help="Result JSON files to rank")
    lb.add_argument("--metric", default="ebitda",
                    choices=["ebitda", "reward", "stockout", "nps"],
                    help="Ranking metric (default: ebitda margin — the business "
                         "outcome; 'reward' = the RL training signal)")
    lb.add_argument("--weights", type=str, default="1-2-3",
                    help="Display label for the weighting (weights come from "
                         "economics.DIFFICULTY_WEIGHTS)")

    args = parser.parse_args()

    if args.command == "baselines":
        return cmd_baselines(args)
    elif args.command == "frontier":
        return cmd_frontier(args)
    elif args.command == "trace":
        return cmd_trace(args)
    elif args.command == "compare":
        return cmd_compare(args)
    elif args.command == "plot":
        return cmd_plot(args)
    elif args.command == "human-baseline":
        return cmd_human_baseline(args)
    elif args.command == "leaderboard":
        return cmd_leaderboard(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
