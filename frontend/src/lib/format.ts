const inrCurrencyFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const inrIntegerFormatter = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0,
});

export function toNum(val: string | number | null | undefined, fallback = 0): number {
  if (val === null || val === undefined || val === "") return fallback;
  const parsed = typeof val === "number" ? val : Number(val);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function formatINR(val: string | number | null | undefined): string {
  const num = toNum(val, 0);
  return inrCurrencyFormatter.format(num);
}

export function formatPrice(val: string | number | null | undefined): string {
  if (val === null || val === undefined || val === "") return "—";
  const num = toNum(val, NaN);
  if (!Number.isFinite(num)) return "—";
  return `₹${num.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatSignedINR(val: string | number | null | undefined): string {
  const num = toNum(val, 0);
  const absFormatted = inrCurrencyFormatter.format(Math.abs(num));
  if (num > 0.004) return `+${absFormatted}`;
  if (num < -0.004) return `-${absFormatted}`;
  return absFormatted;
}

export function formatSignedPct(val: string | number | null | undefined): string {
  const num = toNum(val, 0);
  if (num > 0.004) return `+${num.toFixed(2)}%`;
  if (num < -0.004) return `${num.toFixed(2)}%`;
  return `0.00%`;
}

export function formatQty(val: number | string | null | undefined): string {
  const num = Math.trunc(toNum(val, 0));
  return inrIntegerFormatter.format(num);
}

export function formatCountdown(seconds: number): string {
  const clamped = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(clamped / 60);
  const secs = clamped % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export function snapToTick(price: number, tickSize = 0.05): number {
  if (!Number.isFinite(price) || price <= 0) return tickSize;
  const ticks = Math.round(price / tickSize);
  return Number((Math.max(1, ticks) * tickSize).toFixed(2));
}

export function computeNetWorthFromBuckets(params: {
  availableCash: number;
  orderReservedCash: number;
  shortProceedsLocked: number;
  shortMarginLocked: number;
  longMarketValue: number;
  shortBuybackLiability: number;
  unfundedSettlementDebt: number;
}): number {
  return Number(
    (
      params.availableCash +
      params.orderReservedCash +
      params.shortProceedsLocked +
      params.shortMarginLocked +
      params.longMarketValue -
      params.shortBuybackLiability -
      params.unfundedSettlementDebt
    ).toFixed(4)
  );
}

export function isIntentPermittedInStatus(status: string, intent: string): boolean {
  if (status === "MAIN_TRADING") return true;
  if (status === "SHORT_SETTLEMENT") {
    return intent === "SELL_LONG" || intent === "BUY_TO_COVER";
  }
  return false;
}
