"use client";

import React from "react";
import { formatPrice, formatQty, toNum } from "@/lib/format";
import { useTerminalStore } from "@/store/terminalStore";

export function OrderBookLadder() {
  const orderBook = useTerminalStore((s) => s.orderBook);
  const selectedSymbol = useTerminalStore((s) => s.selectedSymbol);
  const stocks = useTerminalStore((s) => s.stocks);
  const setTicketFromBook = useTerminalStore((s) => s.setTicketFromBook);

  const stock = stocks.find((s) => s.symbol === selectedSymbol);
  const asks = [...(orderBook?.asks || [])].slice(0, 8).reverse(); // Highest ask at top, lowest ask right above spread
  const bids = (orderBook?.bids || []).slice(0, 8);

  const maxQty = Math.max(
    1,
    ...asks.map((l) => l.quantity),
    ...bids.map((l) => l.quantity)
  );

  return (
    <div className="bg-terminal-panel border border-terminal-border rounded flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-terminal-border flex items-center justify-between bg-[#090D15]">
        <span className="text-xs font-bold uppercase tracking-wider text-white">
          L2 Order Book • <span className="text-terminal-orange font-mono">{selectedSymbol}</span>
        </span>
        <span className="text-[10px] text-terminal-muted font-mono">CLICK PX TO FILL TICKET</span>
      </div>

      <div className="grid grid-cols-3 px-3 py-1 text-[10px] font-mono uppercase text-terminal-muted border-b border-terminal-border/60">
        <span>Price (₹)</span>
        <span className="text-right">Shares</span>
        <span className="text-right">Orders</span>
      </div>

      {/* Asks (Sell Liquidity) */}
      <div className="divide-y divide-terminal-border/30 font-mono text-xs">
        {asks.length === 0 ? (
          <div className="py-4 text-center text-[11px] text-terminal-muted italic">
            No resting sell orders
          </div>
        ) : (
          asks.map((lvl) => {
            const pct = Math.min(100, (lvl.quantity / maxQty) * 100);
            return (
              <button
                key={`ask-${lvl.price}`}
                type="button"
                onClick={() => setTicketFromBook(lvl.price, "BUY_LONG")}
                className="relative w-full grid grid-cols-3 px-3 py-1 text-left hover:bg-rose-500/10 transition"
              >
                <div
                  className="absolute inset-y-0 right-0 bg-rose-500/12 pointer-events-none"
                  style={{ width: `${pct}%` }}
                />
                <span className="relative text-terminal-ask font-semibold tabular-nums">
                  {Number(lvl.price).toFixed(2)}
                </span>
                <span className="relative text-right text-slate-200 tabular-nums">
                  {formatQty(lvl.quantity)}
                </span>
                <span className="relative text-right text-terminal-muted tabular-nums">
                  {lvl.order_count}
                </span>
              </button>
            );
          })
        )}
      </div>

      {/* Spread & Reference Strip */}
      <div className="px-3 py-1.5 bg-[#070A10] border-y border-terminal-border flex items-center justify-between font-mono text-[11px]">
        <div>
          <span className="text-terminal-muted">SPREAD: </span>
          <span className="text-white font-semibold">
            {orderBook?.spread ? `₹${Number(orderBook.spread).toFixed(2)}` : "—"}
          </span>
        </div>
        <div>
          <span className="text-terminal-muted">REF: </span>
          <span className="text-terminal-orange font-bold">
            {formatPrice(toNum(stock?.fundamental_ref_price, 1000))}
          </span>
        </div>
      </div>

      {/* Bids (Buy Liquidity) */}
      <div className="divide-y divide-terminal-border/30 font-mono text-xs">
        {bids.length === 0 ? (
          <div className="py-4 text-center text-[11px] text-terminal-muted italic">
            No resting buy orders
          </div>
        ) : (
          bids.map((lvl) => {
            const pct = Math.min(100, (lvl.quantity / maxQty) * 100);
            return (
              <button
                key={`bid-${lvl.price}`}
                type="button"
                onClick={() => setTicketFromBook(lvl.price, "SELL_LONG")}
                className="relative w-full grid grid-cols-3 px-3 py-1 text-left hover:bg-emerald-500/10 transition"
              >
                <div
                  className="absolute inset-y-0 right-0 bg-emerald-500/12 pointer-events-none"
                  style={{ width: `${pct}%` }}
                />
                <span className="relative text-terminal-bid font-semibold tabular-nums">
                  {Number(lvl.price).toFixed(2)}
                </span>
                <span className="relative text-right text-slate-200 tabular-nums">
                  {formatQty(lvl.quantity)}
                </span>
                <span className="relative text-right text-terminal-muted tabular-nums">
                  {lvl.order_count}
                </span>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
