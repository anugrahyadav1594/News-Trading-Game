"use client";

import React, { useState } from "react";
import { formatINR, formatPrice, formatQty } from "@/lib/format";
import { useTerminalStore } from "@/store/terminalStore";

export function HistoryView() {
  const orders = useTerminalStore((s) => s.orders);
  const trades = useTerminalStore((s) => s.trades);
  const [statusFilter, setStatusFilter] = useState<string>("ALL");

  const filteredOrders = orders.filter((o) =>
    statusFilter === "ALL" ? true : o.status === statusFilter
  );

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-4">
      {/* Orders History */}
      <div className="bg-terminal-panel border border-terminal-border rounded overflow-hidden">
        <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-white">
            Complete Order Lifecycle Audit ({filteredOrders.length})
          </span>
          <div className="flex items-center gap-1 font-mono text-[10px]">
            {["ALL", "OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "EXPIRED"].map((st) => (
              <button
                key={st}
                onClick={() => setStatusFilter(st)}
                className={`px-2 py-1 rounded border ${
                  statusFilter === st
                    ? "bg-terminal-orange text-black font-bold border-terminal-orange"
                    : "bg-terminal-elevated border-terminal-border text-terminal-muted hover:text-white"
                }`}
              >
                {st}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto max-h-[340px]">
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-3 py-2">Submitted</th>
                <th className="px-3 py-2">Symbol</th>
                <th className="px-3 py-2">Intent / Type</th>
                <th className="px-3 py-2 text-right">Limit Px</th>
                <th className="px-3 py-2 text-right">Filled / Qty</th>
                <th className="px-3 py-2 text-right">Avg Fill Px</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 font-sans">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {filteredOrders.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-terminal-muted font-sans">
                    No orders match this status filter.
                  </td>
                </tr>
              ) : (
                filteredOrders.map((o) => (
                  <tr key={o.order_id} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-1.5 text-terminal-muted">
                      {new Date(o.submitted_at).toLocaleTimeString("en-IN", { hour12: false })}
                    </td>
                    <td className="px-3 py-1.5 font-bold text-white">{o.symbol}</td>
                    <td className="px-3 py-1.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          o.side === "BUY"
                            ? "bg-emerald-500/15 text-emerald-300"
                            : "bg-rose-500/15 text-rose-300"
                        }`}
                      >
                        {o.intent} ({o.price_type})
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {o.limit_price ? formatPrice(o.limit_price) : "MKT"}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {o.filled_quantity} / {o.quantity}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {o.avg_fill_price ? formatPrice(o.avg_fill_price) : "—"}
                    </td>
                    <td className="px-3 py-1.5 text-amber-200">{o.status}</td>
                    <td className="px-3 py-1.5 font-sans text-terminal-muted text-[11px]">
                      {o.cancel_reason || o.reject_reason || (o.is_forced_liquidation ? "Forced Margin Cover" : "—")}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Executed Trades Tape */}
      <div className="bg-terminal-panel border border-terminal-border rounded overflow-hidden">
        <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] flex justify-between items-center">
          <span className="text-xs font-bold uppercase tracking-wider text-white">
            Executed Peer-to-Peer Trades ({trades.length})
          </span>
          <span className="text-[10px] font-mono text-terminal-muted">
            COUNTERPARTY SEAT ANONYMIZED FOR FAIR COMPETITION
          </span>
        </div>
        <div className="overflow-x-auto max-h-[340px]">
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-3 py-2">Executed At</th>
                <th className="px-3 py-2">Symbol</th>
                <th className="px-3 py-2">Execution Role</th>
                <th className="px-3 py-2 text-right">Resting Match Px</th>
                <th className="px-3 py-2 text-right">Shares</th>
                <th className="px-3 py-2 text-right">Gross Notional</th>
                <th className="px-3 py-2 text-right">Peer Seat Code</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-terminal-muted font-sans">
                    No executed peer-to-peer fills recorded yet.
                  </td>
                </tr>
              ) : (
                trades.map((t) => (
                  <tr key={t.trade_id} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-1.5 text-terminal-muted">
                      {new Date(t.executed_at).toLocaleTimeString("en-IN", { hour12: false })}
                    </td>
                    <td className="px-3 py-1.5 font-bold text-white">{t.symbol}</td>
                    <td className="px-3 py-1.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          t.role === "BUYER"
                            ? "bg-emerald-500/15 text-emerald-300"
                            : "bg-rose-500/15 text-rose-300"
                        }`}
                      >
                        {t.role}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPrice(t.price)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatQty(t.quantity)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatINR(t.notional)}</td>
                    <td className="px-3 py-1.5 text-right text-terminal-orange font-bold">
                      {t.counterparty_code}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
