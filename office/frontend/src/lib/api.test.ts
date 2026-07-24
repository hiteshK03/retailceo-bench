import { describe, it, expect, vi } from "vitest";
import { sendDecisions } from "./api";

describe("sendDecisions", () => {
  it("sends a JSON frame with the week and decisions", () => {
    const send = vi.fn();
    const socket = { send } as unknown as WebSocket;
    const decisions = [
      { proposal_id: "S-1", verdict: "approve" },
      { proposal_id: "S-2", verdict: "modify", modified_params: { qty: 500 } },
    ];
    sendDecisions(socket, 3, decisions);
    expect(send).toHaveBeenCalledTimes(1);
    expect(JSON.parse(send.mock.calls[0][0])).toEqual({ week: 3, decisions });
  });
});
