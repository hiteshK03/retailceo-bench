"""Wire types for the RetailCEO OpenEnv environment.

The action interface is *text-native*: the agent returns the raw completion it
would produce for the weekly brief, exactly as a frontier/OSS model does at
eval time.  The environment parses it internally with the same
``retailceo.prompts.parse_response`` the benchmark uses, so a policy trained
against this env faces an identical contract to the benchmark.

Observation carries the rendered weekly brief (``prompt``) plus a handful of
surfaced scalars for convenience/logging.  Everything needed to drive the next
step is in ``prompt``; the scalars are redundant read-only conveniences.
"""

from __future__ import annotations

from openenv.core.env_server.types import Action, Observation
from pydantic import Field


class CEOTextAction(Action):
    """One weekly CEO decision, as raw model text.

    ``completion`` is the model's full output for the current weekly brief.  It
    should contain a JSON object inside ``<action>...</action>`` tags (see the
    system prompt in ``retailceo.prompts``).  The environment runs the standard
    tolerant parser over it, so partial/truncated output degrades gracefully to
    the ``request_info`` fallback rather than erroring.
    """

    completion: str = Field(
        ...,
        description="Raw model completion for the weekly brief; must contain an "
        "<action>{...}</action> JSON block.",
    )


class CEOTextObservation(Observation):
    """The weekly brief presented to the CEO, plus surfaced KPI scalars.

    ``prompt`` is the full text the policy should condition on (identical to
    what the benchmark's ``render_observation`` produces).  ``done`` and
    ``reward`` come from the OpenEnv base class.  The scalar fields mirror the
    current KPI snapshot so trainers can log/shape without re-parsing the text.
    ``parse`` (in ``metadata``) reports how the *previous* action parsed.
    """

    prompt: str = Field(default="", description="Rendered weekly brief to condition on.")
    week: int = Field(default=0, description="1-indexed week of the episode.")
    max_weeks: int = Field(default=0, description="Total weeks in the episode.")
    inbox_size: int = Field(default=0, description="Number of proposals this week.")

    # Surfaced KPI scalars (read-only convenience; redundant with `prompt`).
    ebitda_margin_pct: float = Field(default=0.0)
    cash_inr: float = Field(default=0.0)
    stockout_rate_pct: float = Field(default=0.0)
    nps: float = Field(default=0.0)
    revenue_inr: float = Field(default=0.0)
