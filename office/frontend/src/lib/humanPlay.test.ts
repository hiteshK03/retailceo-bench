import { describe, it, expect } from "vitest";
import { allDecided, buildDecisions } from "./humanPlay";
import type { Proposal, WeekPayload } from "../types";

function proposal(id: string, action = "po.place"): Proposal {
  return {
    proposal_id: id,
    dept: "supply_chain",
    action,
    params: { qty: 1000 },
    cost_inr: -1000,
    urgency: "med",
    reasoning: "",
    week_submitted: 1,
  };
}

function week(ids: string[]): WeekPayload {
  return { week: 1, active_crises: [], inbox: ids.map((id) => proposal(id)) };
}

describe("allDecided", () => {
  it("is false when the week is undefined", () => {
    expect(allDecided(undefined, {})).toBe(false);
  });

  it("is false for an empty inbox", () => {
    expect(allDecided(week([]), {})).toBe(false);
  });

  it("is false while any proposal is undecided", () => {
    expect(allDecided(week(["A", "B"]), { A: { verdict: "approve" } })).toBe(false);
  });

  it("is true once every proposal has a verdict", () => {
    const pending = { A: { verdict: "approve" }, B: { verdict: "reject" } };
    expect(allDecided(week(["A", "B"]), pending)).toBe(true);
  });
});

describe("buildDecisions", () => {
  it("returns an empty list when there is no week", () => {
    expect(buildDecisions(undefined, {})).toEqual([]);
  });

  it("defaults untouched proposals to request_info", () => {
    const decisions = buildDecisions(week(["A", "B"]), { A: { verdict: "approve" } });
    expect(decisions).toEqual([
      { proposal_id: "A", verdict: "approve", modified_params: undefined },
      { proposal_id: "B", verdict: "request_info", modified_params: undefined },
    ]);
  });

  it("carries modified_params through for a modify verdict", () => {
    const pending = { A: { verdict: "modify", modified_params: { qty: 500 } } };
    const decisions = buildDecisions(week(["A"]), pending);
    expect(decisions[0]).toEqual({
      proposal_id: "A",
      verdict: "modify",
      modified_params: { qty: 500 },
    });
  });

  it("preserves inbox order", () => {
    const decisions = buildDecisions(week(["C", "A", "B"]), {});
    expect(decisions.map((d) => d.proposal_id)).toEqual(["C", "A", "B"]);
  });
});
