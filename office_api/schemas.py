"""Pydantic contracts for the Retail CEO Office API.

Diverged from the SimMart Office schema: the bench exposes only pure-Python
scripted policies (no frontier, no trained checkpoint) and 12-week episodes
with a difficulty selector, so the run config is intentionally small.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# Only the bench's scripted / pure-Python policies are exposed. No frontier
# (Anthropic/OpenAI) and no trained checkpoint — this must run key-free on a
# free CPU Space.
PolicyKind = Literal[
    "heuristic",
    "oracle",
    "all_approve",
    "random",
]

Difficulty = Literal["easy", "medium", "hard"]


class RunConfig(BaseModel):
    """User-supplied configuration for one live CEO run."""

    seed: int = Field(default=42, ge=0)
    policy: PolicyKind = "heuristic"
    difficulty: Difficulty = "medium"
    weeks: int = Field(default=12, ge=1, le=52)
    mode: Literal["auto", "human"] = "auto"
    player_handle: Optional[str] = Field(default=None, max_length=64)


class RunCreated(BaseModel):
    run_id: str
    status: str
    config: RunConfig


class RunState(BaseModel):
    run_id: str
    status: str
    config: RunConfig
    latest_event: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)


class HumanWeekDecisions(BaseModel):
    """One week's decisions submitted by a human player over the socket."""

    week: int = Field(..., ge=1)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    journal: str = Field(default="")
    played_at: Optional[str] = Field(default=None, description="Client ISO8601")
