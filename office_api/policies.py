"""Policy construction for live Retail CEO Office runs.

Exposes ONLY the bench's scripted / pure-Python baseline policies from
``eval.policies``. No frontier API policies and no torch/vLLM — the default
demo runs CPU-only and key-free.
"""

from __future__ import annotations

from eval.policies import (
    AllApproveCEO,
    CEOPolicy,
    HeuristicCEO,
    OracleCEO,
    RandomCEO,
)

from .schemas import RunConfig


def build_policy(config: RunConfig) -> CEOPolicy:
    """Build a scripted CEO policy from API configuration."""

    if config.policy == "random":
        return RandomCEO(seed=config.seed)
    if config.policy == "all_approve":
        return AllApproveCEO()
    if config.policy == "heuristic":
        return HeuristicCEO()
    if config.policy == "oracle":
        return OracleCEO()
    raise ValueError(f"Unsupported policy: {config.policy}")
