# Contributing to RetailCEO-Bench

Contributions are welcome — **pull requests, issues, and leaderboard
submissions all help.** Whether you're adding a model to the leaderboard, fixing
a bug in the simulation, improving the reward calibration, or extending the
OpenEnv training environment, please read this guide first.

## Ways to contribute

- **Add a model to the leaderboard** — run the official protocol and open a PR
  with the result JSON + traces (see [Leaderboard submissions](#leaderboard-submissions)).
- **Improve the simulation** — new crises, departments, SKUs, economic
  dynamics, or difficulty calibration.
- **Improve the RL environment** — anything under `retailceo_env/` (the OpenEnv
  server/client).
- **Fix bugs / add tests** — especially reward-integrity and reproducibility.
- **Docs** — clarify anything that tripped you up.

## Development setup

```bash
git clone https://github.com/hiteshK03/retailceo-bench.git
cd retailceo-bench

pip install -e ".[dev]"            # core + pytest
pip install -e ".[dev,eval]"       # + anthropic/openai for frontier eval
pip install -e ".[dev,openenv]"    # + openenv for the RL env + its tests
```

Requires Python >= 3.10.

## Running tests

```bash
pytest tests/ -v
```

The suite must stay **green on Python 3.10–3.12, Linux + macOS** (CI enforces
this). Key invariants:

- **Determinism** — same seed ⇒ identical reward sequence and final cash.
- **Cross-platform reproducibility** — hardcoded reference values for
  `seed=42` approve-all / reject-all episodes (`tests/test_environment.py`).
  If your change intentionally alters simulation or reward logic, **regenerate
  these reference values deliberately** and call it out in the PR — a shift
  there means scoring changed.
- **Reward bounds** — total episode reward stays within theoretical bounds.
- **OpenEnv parity** — the text-action adapter must reproduce the core
  simulator's rewards exactly (`tests/test_openenv.py`).

If you change reward weights or components, expect to update reference values
and the reward documentation in the README together.

## Code style

- Standard library + `pydantic` for the core package; keep the core dependency
  footprint minimal (the simulator must stay importable with just `pydantic`).
- Type hints on public functions; `from __future__ import annotations` at the
  top of modules.
- Keep simulation logic in `retailceo/`, evaluation in `eval/`, the RL env in
  `retailceo_env/`. Don't let them leak into each other — the OpenEnv adapter
  must remain thin glue over `retailceo`, not a fork of it.
- No comments that restate the code; comment the *why* when it's non-obvious.

## Pull request standards

1. **One focused change per PR.** Separate refactors from behavior changes.
2. **Tests pass locally** (`pytest tests/ -v`) before you open the PR.
3. **Add tests** for new behavior; **update reference values** for intentional
   scoring changes.
4. **Describe the why**, not just the what. If it touches reward or simulation
   dynamics, explain the expected effect on baselines.
5. **Keep the diff clean** — no scratch files, no committed trace artifacts
   outside `results/`.

## Leaderboard submissions

Run the **full official protocol** and submit the result JSON + traces:

```bash
python -m eval.cli frontier --model <your-model> --provider <anthropic|openai> \
  --protocol full --out results/<model-name>_full.json
```

Submission rules (see the README's Evaluation Protocol for the authoritative
list): temperature 0.0, **no parse retries** (`--parse-retries 0`, the
default), the default system prompt, and full trace JSONs for verification.
Open a PR adding your result file under `results/` and your row to the README
leaderboard table.

## Adding an OpenEnv training environment variant

The RL environment lives in `retailceo_env/` and follows the OpenEnv
`Environment` / `EnvClient` conventions. If you add a variant (e.g. a
structured-action interface alongside the text one), mirror the existing layout
(`models.py`, `client.py`, `server/`) and **keep the train/eval seed split
intact** — reserved eval seeds (42–51) must remain refused for training by
default. Add a parity test proving your variant scores identically to the
benchmark.

## Reporting bugs / requesting features

Open a GitHub issue with a minimal repro (seed, difficulty, and the command you
ran). For reward/simulation surprises, include the trace JSON if you can.

## License

By contributing you agree that your contributions are licensed under the
project's [MIT License](./LICENSE).
