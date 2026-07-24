import { describe, it, expect } from "vitest";
import { formatInr, formatNumber, verdictLabel, verdictClass, decisionsById } from "./format";

describe("formatInr", () => {
  it("returns a dash for missing/NaN", () => {
    expect(formatInr(undefined)).toBe("-");
    expect(formatInr(NaN)).toBe("-");
  });

  it("scales to Cr and L", () => {
    expect(formatInr(2e7)).toBe("₹2.00Cr");
    expect(formatInr(5e5)).toBe("₹5.0L");
  });

  it("keeps the sign for negatives", () => {
    expect(formatInr(-2e7)).toBe("-₹2.00Cr");
  });
});

describe("formatNumber", () => {
  it("formats to the requested digits, dash for missing", () => {
    expect(formatNumber(1.2345, 2)).toBe("1.23");
    expect(formatNumber(undefined)).toBe("-");
  });
});

describe("verdictLabel / verdictClass", () => {
  it("labels underscores as spaces and defaults to pending", () => {
    expect(verdictLabel("request_info")).toBe("request info");
    expect(verdictLabel(undefined)).toBe("pending");
  });

  it("maps verdicts to CSS classes", () => {
    expect(verdictClass("approve")).toBe("approve");
    expect(verdictClass("request_info")).toBe("info");
    expect(verdictClass("modify")).toBe("modify");
    expect(verdictClass(undefined)).toBe("pending");
  });
});

describe("decisionsById", () => {
  it("keys decisions by proposal_id", () => {
    const map = decisionsById([
      { proposal_id: "A", verdict: "approve" },
      { proposal_id: "B", verdict: "reject" },
    ]);
    expect(map.A.verdict).toBe("approve");
    expect(map.B.verdict).toBe("reject");
  });

  it("handles an empty/omitted list", () => {
    expect(decisionsById()).toEqual({});
  });
});
