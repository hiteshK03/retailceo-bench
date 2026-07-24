import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProposalPanel } from "./ProposalPanel";
import type { Proposal, WeekPayload } from "../types";

function proposal(id: string, action = "po.place", extra: Partial<Proposal> = {}): Proposal {
  return {
    proposal_id: id,
    dept: "supply_chain",
    action,
    params: { qty: 1000 },
    cost_inr: -1000,
    urgency: "med",
    reasoning: "restock",
    week_submitted: 1,
    ...extra,
  };
}

function week(props: Proposal[]): WeekPayload {
  return { week: 1, active_crises: [], inbox: props };
}

describe("ProposalPanel — read-only (spectator) mode", () => {
  it("renders proposals without verdict buttons", () => {
    render(<ProposalPanel week={week([proposal("S-1")])} />);
    expect(screen.getByText("S-1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("shows the empty-state copy with no proposals", () => {
    render(<ProposalPanel week={week([])} />);
    expect(screen.getByText(/No proposals loaded yet/i)).toBeInTheDocument();
  });
});

describe("ProposalPanel — interactive mode", () => {
  it("renders Approve / Reject / Info buttons per proposal", () => {
    render(
      <ProposalPanel week={week([proposal("S-1")])} interactive pendingVerdicts={{}} onSetVerdict={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Info" })).toBeInTheDocument();
  });

  it("calls onSetVerdict with the chosen verdict on click", async () => {
    const onSet = vi.fn();
    render(
      <ProposalPanel week={week([proposal("S-1")])} interactive pendingVerdicts={{}} onSetVerdict={onSet} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(onSet).toHaveBeenCalledWith("S-1", "reject");
  });

  it("marks the pending verdict button active", () => {
    render(
      <ProposalPanel
        week={week([proposal("S-1")])}
        interactive
        pendingVerdicts={{ "S-1": { verdict: "approve" } }}
        onSetVerdict={vi.fn()}
      />,
    );
    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toHaveClass("active");
    expect(screen.getByRole("button", { name: "Reject" })).not.toHaveClass("active");
  });

  it("shows a qty modify input for PO proposals that emits a modify verdict", async () => {
    const onSet = vi.fn();
    render(
      <ProposalPanel week={week([proposal("S-1", "po.place")])} interactive pendingVerdicts={{}} onSetVerdict={onSet} />,
    );
    const qty = screen.getByRole("spinbutton");
    await userEvent.clear(qty);
    await userEvent.type(qty, "500");
    expect(onSet).toHaveBeenLastCalledWith("S-1", "modify", { qty: 500 });
  });

  it("does NOT show a qty input for non-PO proposals", () => {
    render(
      <ProposalPanel
        week={week([proposal("G-1", "campaign.launch", { params: { spend_inr: 100000 } })])}
        interactive
        pendingVerdicts={{}}
        onSetVerdict={vi.fn()}
      />,
    );
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("groups proposals by department heading", () => {
    render(
      <ProposalPanel
        week={week([
          proposal("S-1", "po.place", { dept: "supply_chain" }),
          proposal("G-1", "campaign.launch", { dept: "growth", params: {} }),
        ])}
        interactive
        pendingVerdicts={{}}
        onSetVerdict={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "Supply Chain" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Growth" })).toBeInTheDocument();
    // The growth card should have no qty input; the supply_chain one should.
    const growth = screen.getByRole("heading", { name: "Growth" }).closest("section")!;
    expect(within(growth).queryByRole("spinbutton")).not.toBeInTheDocument();
  });
});
