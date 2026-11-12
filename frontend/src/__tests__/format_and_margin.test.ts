import { describe, expect, it } from "vitest";
import {
  computeNetWorthFromBuckets,
  formatCountdown,
  formatINR,
  isIntentPermittedInStatus,
  snapToTick,
} from "../lib/format";

describe("MTT Frontend Financial Formatting & Phase Invariants", () => {
  it("formats starting allocation in Indian Rupee numbering (₹10,00,000.00)", () => {
    const formatted = formatINR(1000000);
    expect(formatted).toContain("10,00,000.00");
  });

  it("snaps arbitrary prices to ₹0.05 tick increments", () => {
    expect(snapToTick(1000.024, 0.05)).toBe(1000.0);
    expect(snapToTick(1000.026, 0.05)).toBe(1000.05);
    expect(snapToTick(1012.78, 0.05)).toBe(1012.8);
  });

  it("enforces zero double-counting in 4-bucket short-sale net worth math", () => {
    // Player starts with ₹5,00,000 cash + ₹5,00,000 longs = ₹10,00,000.
    // Player short sells 50 shares @ ₹1,000 -> ₹25,000 margin locked from avail cash, ₹50,000 proceeds locked, ₹50,000 liability.
    const nwAtEntry = computeNetWorthFromBuckets({
      availableCash: 475000,
      orderReservedCash: 0,
      shortProceedsLocked: 50000,
      shortMarginLocked: 25000,
      longMarketValue: 500000,
      shortBuybackLiability: 50000,
      unfundedSettlementDebt: 0,
    });
    expect(nwAtEntry).toBe(1000000);

    // If shorted stock rises to ₹1,100 -> liability = ₹55,000 -> Net Worth = ₹9,95,000
    const nwAfterAdverseMove = computeNetWorthFromBuckets({
      availableCash: 475000,
      orderReservedCash: 0,
      shortProceedsLocked: 50000,
      shortMarginLocked: 25000,
      longMarketValue: 500000,
      shortBuybackLiability: 55000,
      unfundedSettlementDebt: 0,
    });
    expect(nwAfterAdverseMove).toBe(995000);
  });

  it("permits only SELL_LONG and BUY_TO_COVER during Phase B SHORT_SETTLEMENT", () => {
    expect(isIntentPermittedInStatus("MAIN_TRADING", "BUY_LONG")).toBe(true);
    expect(isIntentPermittedInStatus("MAIN_TRADING", "SHORT_SELL")).toBe(true);

    expect(isIntentPermittedInStatus("SHORT_SETTLEMENT", "BUY_LONG")).toBe(false);
    expect(isIntentPermittedInStatus("SHORT_SETTLEMENT", "SHORT_SELL")).toBe(false);
    expect(isIntentPermittedInStatus("SHORT_SETTLEMENT", "SELL_LONG")).toBe(true);
    expect(isIntentPermittedInStatus("SHORT_SETTLEMENT", "BUY_TO_COVER")).toBe(true);

    expect(isIntentPermittedInStatus("COMPLETED", "BUY_TO_COVER")).toBe(false);
    expect(formatCountdown(2700)).toBe("45:00");
    expect(formatCountdown(300)).toBe("05:00");
  });
});
