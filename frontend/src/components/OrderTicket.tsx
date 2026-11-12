"use client";

import React, { useEffect, useState } from "react";
import { AlertCircle, Lock, Zap } from "lucide-react";
import { exchangeApi } from "@/lib/api";
import { formatINR, formatPrice, formatQty, isIntentPermittedInStatus, snapToTick, toNum } from "@/lib/format";
import { useAuthStore } from "@/store/authStore";
import { useTerminalStore } from "@/store/terminalStore";
import type { OrderIntent, OrderPriceType } from "@/types/exchange";

const INTENTS: Array<{
  id: OrderIntent;
  label: string;
  shortDesc: string;
  activeClass: string;
}> = [
  {
    id: "BUY_LONG",
    label: "BUY LONG",
    shortDesc: "Open / add long",
    activeClass: "bg-emerald-600 text-white border-emerald-400",
  },
  {
    id: "SELL_LONG",
    label: "SELL LONG",
    shortDesc: "Sell owned shares",
    activeClass: "bg-rose-600 text-white border-rose-400",
  },
  {
    id: "SHORT_SELL",
    label: "SHORT SELL",
    shortDesc: "Borrow & sell",
    activeClass: "bg-terminal-orange text-black font-black border-amber-300",
  },
  {
    id: "BUY_TO_COVER",
    label: "BUY COVER",
    shortDesc: "Close short debt",
    activeClass: "bg-sky-500 text-black font-black border-sky-300",
  },
];

export function OrderTicket() {
  const user = useAuthStore((s) => s.user);
  const activeGame = useTerminalStore((s) => s.activeGame);
  const clock = useTerminalStore((s) => s.clock);
  const selectedSymbol = useTerminalStore((s) => s.selectedSymbol);
  const stocks = useTerminalStore((s) => s.stocks);
  const portfolio = useTerminalStore((s) => s.portfolio);
  const ticketDraft = useTerminalStore((s) => s.ticketDraft);
  const pushToast = useTerminalStore((s) => s.pushToast);
  const refreshPrivateData = useTerminalStore((s) => s.refreshPrivateData);
  const refreshSymbolData = useTerminalStore((s) => s.refreshSymbolData);

  const [intent, setIntent] = useState<OrderIntent>(ticketDraft.intent);
  const [priceType, setPriceType] = useState<OrderPriceType>("LIMIT");
  const [limitPrice, setLimitPrice] = useState<string>(ticketDraft.limitPrice);
  const [quantity, setQuantity] = useState<string>(ticketDraft.quantity);
  const [tif, setTif] = useState<"GTC" | "IOC" | "GTD">("GTC");
  const [expiresSec, setExpiresSec] = useState<string>("120");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setIntent(ticketDraft.intent);
    setLimitPrice(ticketDraft.limitPrice);
    setQuantity(ticketDraft.quantity);
  }, [ticketDraft]);

  const status = clock?.status || activeGame?.status || "LOBBY";
  // Auto-switch intent to BUY_TO_COVER or SELL_LONG when Phase B starts
  useEffect(() => {
    if (status === "SHORT_SETTLEMENT" && (intent === "BUY_LONG" || intent === "SHORT_SELL")) {
      setIntent("BUY_TO_COVER");
    }
  }, [status, intent]);

  const stock = stocks.find((s) => s.symbol === selectedSymbol);
  const longPos = portfolio?.long_holdings.find((h) => h.symbol === selectedSymbol);
  const shortPos = portfolio?.short_positions.find((sp) => sp.symbol === selectedSymbol);

  const qtyInt = Math.max(0, Math.trunc(toNum(quantity, 0)));
  const refAnchor = toNum(stock?.last_traded_price || stock?.official_mtm_price, 1000);
  const collarPct = toNum(activeGame?.market_order_collar_pct, 0.1);
  const initMarginRatio = toNum(activeGame?.initial_margin_ratio, 0.5);

  const estExecPx =
    priceType === "LIMIT"
      ? toNum(limitPrice, refAnchor)
      : intent === "BUY_LONG" || intent === "BUY_TO_COVER"
      ? snapToTick(refAnchor * (1 + collarPct))
      : snapToTick(refAnchor * (1 - collarPct));

  const estNotional = qtyInt * estExecPx;
  const estShortMargin = intent === "SHORT_SELL" ? estNotional * initMarginRatio : 0;

  const openCoverableQty = shortPos
    ? Math.max(0, shortPos.borrowed_quantity - shortPos.reserved_cover_quantity)
    : 0;
  const availLongQty = longPos?.available_quantity ?? 0;
  const poolRem = stock?.borrow_pool?.remaining_shares ?? 0;

  const intentAllowed = isIntentPermittedInStatus(status, intent);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeGame) return;
    if (qtyInt <= 0) {
      pushToast({ tone: "error", title: "Invalid Quantity", detail: "Enter a positive integer share quantity." });
      return;
    }

    setSubmitting(true);
    try {
      const snappedLimit =
        priceType === "LIMIT" ? snapToTick(toNum(limitPrice, 1000)).toFixed(2) : null;
      const res = await exchangeApi.placeOrder(activeGame.game_id, {
        symbol: selectedSymbol,
        intent,
        price_type: priceType,
        quantity: qtyInt,
        limit_price: snappedLimit,
        time_in_force: priceType === "MARKET" ? "IOC" : tif,
        expires_in_sec: priceType === "LIMIT" && tif === "GTD" ? Math.max(5, Math.trunc(toNum(expiresSec, 60))) : null,
      });

      const ord = res.order;
      pushToast({
        tone: ord.status === "FILLED" ? "success" : ord.status === "CANCELLED" ? "warning" : "info",
        title: `${intent} ${qtyInt} ${selectedSymbol} • ${ord.status}`,
        detail:
          res.fills_count > 0
            ? `Matched ${ord.filled_quantity}/${ord.quantity} sh @ avg ₹${Number(ord.avg_fill_price).toFixed(2)} (${res.fills_count} P2P print${res.fills_count > 1 ? "s" : ""})`
            : ord.cancel_reason || `Resting on ${selectedSymbol} book @ ₹${snappedLimit}`,
      });

      await Promise.all([refreshPrivateData(), refreshSymbolData(selectedSymbol)]);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Order Rejected by Exchange",
        detail: err instanceof Error ? err.message : "Failed to submit order",
      });
    } finally {
      setSubmitting(false);
    }
  };

  if (user?.role === "ADMIN") {
    return (
      <div className="bg-terminal-panel border border-terminal-border rounded p-4 text-xs text-terminal-muted space-y-2">
        <div className="font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
          <Lock className="w-3.5 h-3.5 text-terminal-orange" />
          Director Observer Mode
        </div>
        <p>
          Administrators cannot submit personal trading orders (strict separation of Exchange
          Surveillance &amp; Player Execution). Switch to a Player account or open the{" "}
          <strong className="text-terminal-orange">Control Room</strong> to manage news &amp; game phases.
        </p>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-terminal-panel border border-terminal-border rounded flex flex-col overflow-hidden"
    >
      <div className="px-3 py-2 border-b border-terminal-border flex items-center justify-between bg-[#090D15]">
        <span className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5 text-terminal-orange" />
          Order Entry • <span className="font-mono text-terminal-orange">{selectedSymbol}</span>
        </span>
        <span className="text-[10px] font-mono text-terminal-muted">TICK ₹0.05 • INTEGER SHARES</span>
      </div>

      <div className="p-3 space-y-3 text-xs">
        {/* 4 Explicit Order Intents */}
        <div className="grid grid-cols-2 gap-1.5">
          {INTENTS.map((it) => {
            const permitted = isIntentPermittedInStatus(status, it.id);
            const selected = intent === it.id;
            return (
              <button
                key={it.id}
                type="button"
                onClick={() => setIntent(it.id)}
                className={`px-2.5 py-2 rounded border text-left transition relative ${
                  selected
                    ? it.activeClass
                    : permitted
                    ? "bg-terminal-elevated border-terminal-border text-slate-300 hover:border-slate-500"
                    : "bg-[#090C12] border-terminal-border/50 text-slate-600"
                }`}
              >
                <div className="font-mono font-bold text-[11px] flex items-center justify-between">
                  <span>{it.label}</span>
                  {!permitted && <Lock className="w-3 h-3 opacity-70" />}
                </div>
                <div className={`text-[10px] ${selected ? "opacity-90" : "text-terminal-muted"}`}>
                  {it.shortDesc}
                </div>
              </button>
            );
          })}
        </div>

        {/* Price Type Toggle */}
        <div className="grid grid-cols-2 gap-1 bg-[#070A10] p-1 rounded border border-terminal-border font-mono">
          {(["LIMIT", "MARKET"] as const).map((pt) => (
            <button
              key={pt}
              type="button"
              onClick={() => setPriceType(pt)}
              className={`py-1 rounded text-[11px] font-bold transition ${
                priceType === pt
                  ? "bg-terminal-elevated text-white border border-terminal-borderBright"
                  : "text-terminal-muted hover:text-white"
              }`}
            >
              {pt === "LIMIT" ? "LIMIT ORDER" : "MARKET (IOC COLLAR)"}
            </button>
          ))}
        </div>

        {/* Quantity & Limit Price Inputs */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-[10px] uppercase text-terminal-muted mb-1 font-mono">
              Quantity (Shares)
            </label>
            <input
              type="number"
              min={1}
              step={1}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="w-full bg-[#070A10] border border-terminal-borderBright rounded px-2.5 py-1.5 font-mono text-sm text-white focus:outline-none focus:border-terminal-orange"
            />
          </div>

          <div>
            <label className="block text-[10px] uppercase text-terminal-muted mb-1 font-mono">
              {priceType === "LIMIT" ? "Limit Price (₹)" : "Collar Bound (₹)"}
            </label>
            {priceType === "LIMIT" ? (
              <input
                type="number"
                min={0.05}
                step={0.05}
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)}
                className="w-full bg-[#070A10] border border-terminal-borderBright rounded px-2.5 py-1.5 font-mono text-sm text-white focus:outline-none focus:border-terminal-orange"
              />
            ) : (
              <div className="w-full bg-[#070A10]/60 border border-terminal-border rounded px-2.5 py-1.5 font-mono text-sm text-terminal-muted">
                {formatPrice(estExecPx)}
              </div>
            )}
          </div>
        </div>

        {/* Quick Share Presets */}
        <div className="flex items-center gap-1 font-mono text-[10px]">
          {[10, 25, 50, 100].map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => setQuantity(String(q))}
              className="flex-1 py-1 rounded bg-terminal-elevated border border-terminal-border hover:border-terminal-orange text-slate-300"
            >
              {q} sh
            </button>
          ))}
          {intent === "SELL_LONG" && availLongQty > 0 && (
            <button
              type="button"
              onClick={() => setQuantity(String(availLongQty))}
              className="px-2 py-1 rounded bg-rose-500/15 border border-rose-500/40 text-rose-300 font-bold"
            >
              MAX ({availLongQty})
            </button>
          )}
          {intent === "BUY_TO_COVER" && openCoverableQty > 0 && (
            <button
              type="button"
              onClick={() => setQuantity(String(openCoverableQty))}
              className="px-2 py-1 rounded bg-sky-500/15 border border-sky-500/40 text-sky-300 font-bold"
            >
              COVER ALL ({openCoverableQty})
            </button>
          )}
        </div>

        {/* Time in Force for Limit Orders */}
        {priceType === "LIMIT" && (
          <div className="flex items-center gap-2 font-mono text-[11px]">
            <span className="text-terminal-muted text-[10px] uppercase">TIF:</span>
            {(["GTC", "IOC", "GTD"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTif(t)}
                className={`px-2 py-0.5 rounded border text-[10px] ${
                  tif === t
                    ? "border-terminal-orange text-terminal-orange bg-terminal-orange/10 font-bold"
                    : "border-terminal-border text-terminal-muted"
                }`}
              >
                {t}
              </button>
            ))}
            {tif === "GTD" && (
              <input
                type="number"
                min={5}
                max={2700}
                value={expiresSec}
                onChange={(e) => setExpiresSec(e.target.value)}
                className="w-20 bg-[#070A10] border border-terminal-border rounded px-1.5 py-0.5 text-white text-[11px]"
                title="Expiry seconds"
              />
            )}
          </div>
        )}

        {/* Position & Margin Pre-Trade Diagnostics */}
        <div className="bg-[#070A10] border border-terminal-border rounded p-2.5 space-y-1 font-mono text-[11px]">
          <div className="flex justify-between">
            <span className="text-terminal-muted">Est. Order Notional:</span>
            <span className="text-white font-semibold tabular-nums">{formatINR(estNotional)}</span>
          </div>
          {intent === "SHORT_SELL" && (
            <>
              <div className="flex justify-between text-amber-300">
                <span>Initial Margin Lock ({(initMarginRatio * 100).toFixed(0)}%):</span>
                <span className="font-bold tabular-nums">{formatINR(estShortMargin)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-terminal-muted">Central Borrow Pool Rem:</span>
                <span className="text-slate-200 tabular-nums">{formatQty(poolRem)} sh</span>
              </div>
            </>
          )}
          {intent === "SELL_LONG" && (
            <div className="flex justify-between">
              <span className="text-terminal-muted">Owned Avail Long:</span>
              <span className="text-emerald-300 font-semibold">{formatQty(availLongQty)} sh</span>
            </div>
          )}
          {intent === "BUY_TO_COVER" && (
            <div className="flex justify-between">
              <span className="text-terminal-muted">Open Unreserved Short:</span>
              <span className="text-sky-300 font-semibold">{formatQty(openCoverableQty)} sh</span>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-terminal-muted">Available Cash:</span>
            <span className="text-slate-200 tabular-nums">
              {formatINR(portfolio?.available_cash || 0)}
            </span>
          </div>
        </div>

        {/* Phase Lockout Warning */}
        {!intentAllowed && (
          <div className="flex items-start gap-2 p-2 rounded bg-rose-500/10 border border-rose-500/30 text-[11px] text-rose-200">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <span>
              {status === "SHORT_SETTLEMENT"
                ? `${intent} is disabled during Phase B Short Position Settlement. Use BUY COVER or SELL LONG.`
                : `Trading is currently not active (Game Status: ${status}).`}
            </span>
          </div>
        )}

        <button
          type="submit"
          disabled={submitting || !intentAllowed || !activeGame?.joined}
          className={`w-full py-2.5 rounded font-mono font-bold text-xs uppercase tracking-wider transition shadow-lg disabled:opacity-40 disabled:cursor-not-allowed ${
            intent === "BUY_LONG"
              ? "bg-emerald-500 hover:bg-emerald-400 text-black"
              : intent === "SELL_LONG"
              ? "bg-rose-500 hover:bg-rose-400 text-white"
              : intent === "SHORT_SELL"
              ? "bg-terminal-orange hover:bg-terminal-orangeHover text-black"
              : "bg-sky-400 hover:bg-sky-300 text-black"
          }`}
        >
          {submitting
            ? "ROUTING TO MATCHING ENGINE..."
            : !activeGame?.joined
            ? "JOIN TOURNAMENT IN LOBBY FIRST"
            : `SUBMIT ${priceType} ${intent.replace(/_/g, " ")} (${qtyInt} ${selectedSymbol})`}
        </button>
      </div>
    </form>
  );
}
