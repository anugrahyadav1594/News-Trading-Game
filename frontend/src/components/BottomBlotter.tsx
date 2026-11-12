"use client";

import React, { useState } from "react";
import { Check, Edit3, Trash2, X } from "lucide-react";
import { exchangeApi } from "@/lib/api";
import { formatINR, formatPrice, formatQty, formatSignedINR, toNum } from "@/lib/format";
import { useTerminalStore } from "@/store/terminalStore";

export function BottomBlotter() {
  const activeGame = useTerminalStore((s) => s.activeGame);
  const orders = useTerminalStore((s) => s.orders);
  const portfolio = useTerminalStore((s) => s.portfolio);
  const trades = useTerminalStore((s) => s.trades);
  const pushToast = useTerminalStore((s) => s.pushToast);
  const refreshPrivateData = useTerminalStore((s) => s.refreshPrivateData);
  const refreshSymbolData = useTerminalStore((s) => s.refreshSymbolData);
  const setSelectedSymbol = useTerminalStore((s) => s.setSelectedSymbol);
  const setTicketFromBook = useTerminalStore((s) => s.setTicketFromBook);

  const [tab, setTab] = useState<"OPEN_ORDERS" | "LONGS" | "SHORTS" | "TRADES">("OPEN_ORDERS");
  const [editingOrderId, setEditingOrderId] = useState<string | null>(null);
  const [editQty, setEditQty] = useState<string>("");
  const [editPx, setEditPx] = useState<string>("");

  const openOrders = orders.filter((o) => o.status === "OPEN" || o.status === "PARTIALLY_FILLED");
  const activeShorts = (portfolio?.short_positions || []).filter((sp) => sp.borrowed_quantity > 0);
  const longs = portfolio?.long_holdings || [];

  const handleCancel = async (orderId: string, sym: string) => {
    if (!activeGame) return;
    try {
      await exchangeApi.cancelOrder(activeGame.game_id, orderId);
      pushToast({ tone: "info", title: `Cancelled Order (${sym})`, detail: "Unused reservations released." });
      await Promise.all([refreshPrivateData(), refreshSymbolData(sym)]);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Cancel Failed",
        detail: err instanceof Error ? err.message : "Could not cancel order",
      });
    }
  };

  const handleSaveModify = async (orderId: string, sym: string) => {
    if (!activeGame) return;
    try {
      await exchangeApi.modifyOrder(activeGame.game_id, orderId, {
        new_quantity: Math.trunc(toNum(editQty, 1)),
        new_limit_price: Number(editPx).toFixed(2),
      });
      setEditingOrderId(null);
      pushToast({
        tone: "success",
        title: `Replaced Order (${sym})`,
        detail: `Modified to ${editQty} sh @ ₹${Number(editPx).toFixed(2)}`,
      });
      await Promise.all([refreshPrivateData(), refreshSymbolData(sym)]);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Modify Failed",
        detail: err instanceof Error ? err.message : "Could not modify order",
      });
    }
  };

  return (
    <div className="bg-terminal-panel border border-terminal-border rounded flex flex-col overflow-hidden">
      {/* Blotter Tabs */}
      <div className="px-3 border-b border-terminal-border bg-[#090D15] flex items-center gap-2 overflow-x-auto">
        <button
          onClick={() => setTab("OPEN_ORDERS")}
          className={`py-2 px-2.5 text-xs font-semibold border-b-2 transition ${
            tab === "OPEN_ORDERS"
              ? "border-terminal-orange text-terminal-orange"
              : "border-transparent text-terminal-muted hover:text-white"
          }`}
        >
          Open Orders ({openOrders.length})
        </button>
        <button
          onClick={() => setTab("LONGS")}
          className={`py-2 px-2.5 text-xs font-semibold border-b-2 transition ${
            tab === "LONGS"
              ? "border-terminal-orange text-terminal-orange"
              : "border-transparent text-terminal-muted hover:text-white"
          }`}
        >
          Long Holdings ({longs.filter((l) => l.total_quantity > 0).length})
        </button>
        <button
          onClick={() => setTab("SHORTS")}
          className={`py-2 px-2.5 text-xs font-semibold border-b-2 transition ${
            tab === "SHORTS"
              ? "border-terminal-orange text-terminal-orange"
              : "border-transparent text-terminal-muted hover:text-white"
          }`}
        >
          Short Positions &amp; Margin ({activeShorts.length})
        </button>
        <button
          onClick={() => setTab("TRADES")}
          className={`py-2 px-2.5 text-xs font-semibold border-b-2 transition ${
            tab === "TRADES"
              ? "border-terminal-orange text-terminal-orange"
              : "border-transparent text-terminal-muted hover:text-white"
          }`}
        >
          Recent Executions ({trades.length})
        </button>
      </div>

      {/* Tab Content */}
      <div className="overflow-x-auto max-h-[250px]">
        {tab === "OPEN_ORDERS" && (
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-3 py-1.5">Symbol</th>
                <th className="px-3 py-1.5">Intent</th>
                <th className="px-3 py-1.5 text-right">Limit Px</th>
                <th className="px-3 py-1.5 text-right">Filled / Qty</th>
                <th className="px-3 py-1.5">Status</th>
                <th className="px-3 py-1.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {openOrders.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-terminal-muted font-sans">
                    No active resting orders on the peer-to-peer order book.
                  </td>
                </tr>
              ) : (
                openOrders.map((ord) => {
                  const isEditing = editingOrderId === ord.order_id;
                  return (
                    <tr key={ord.order_id} className="hover:bg-white/[0.02]">
                      <td className="px-3 py-1.5 font-bold text-white">{ord.symbol}</td>
                      <td className="px-3 py-1.5">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                            ord.side === "BUY"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : "bg-rose-500/15 text-rose-300"
                          }`}
                        >
                          {ord.intent}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {isEditing ? (
                          <input
                            type="number"
                            step={0.05}
                            value={editPx}
                            onChange={(e) => setEditPx(e.target.value)}
                            className="w-24 bg-[#070A10] border border-terminal-orange rounded px-1.5 py-0.5 text-right text-white"
                          />
                        ) : (
                          formatPrice(ord.limit_price)
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {isEditing ? (
                          <input
                            type="number"
                            min={ord.filled_quantity + 1}
                            step={1}
                            value={editQty}
                            onChange={(e) => setEditQty(e.target.value)}
                            className="w-20 bg-[#070A10] border border-terminal-orange rounded px-1.5 py-0.5 text-right text-white"
                          />
                        ) : (
                          `${ord.filled_quantity} / ${ord.quantity}`
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-amber-300 text-[11px]">{ord.status}</td>
                      <td className="px-3 py-1.5 text-right">
                        {isEditing ? (
                          <div className="inline-flex items-center gap-1">
                            <button
                              onClick={() => handleSaveModify(ord.order_id, ord.symbol)}
                              className="p-1 rounded bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
                              title="Confirm Cancel-and-Replace"
                            >
                              <Check className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => setEditingOrderId(null)}
                              className="p-1 rounded bg-slate-700/40 text-slate-300"
                              title="Abort Edit"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        ) : (
                          <div className="inline-flex items-center gap-1.5">
                            <button
                              onClick={() => {
                                setEditingOrderId(ord.order_id);
                                setEditPx(Number(ord.limit_price || 1000).toFixed(2));
                                setEditQty(String(ord.quantity));
                              }}
                              className="p-1 rounded border border-terminal-border hover:border-terminal-orange text-slate-300 hover:text-white"
                              title="Modify Price / Quantity"
                            >
                              <Edit3 className="w-3 h-3" />
                            </button>
                            <button
                              onClick={() => handleCancel(ord.order_id, ord.symbol)}
                              className="p-1 rounded border border-rose-500/30 hover:bg-rose-500/20 text-rose-400"
                              title="Cancel Order"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}

        {tab === "LONGS" && (
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-3 py-1.5">Symbol</th>
                <th className="px-3 py-1.5 text-right">Avail / Total Sh</th>
                <th className="px-3 py-1.5 text-right">Avg Cost</th>
                <th className="px-3 py-1.5 text-right">MTM Px</th>
                <th className="px-3 py-1.5 text-right">Market Value</th>
                <th className="px-3 py-1.5 text-right">Unrealized P&amp;L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {longs.map((h) => {
                const upnl = toNum(h.unrealized_pnl, 0);
                return (
                  <tr
                    key={h.symbol}
                    onClick={() => setSelectedSymbol(h.symbol)}
                    className="hover:bg-white/[0.03] cursor-pointer"
                  >
                    <td className="px-3 py-1.5 font-bold text-white">{h.symbol}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {formatQty(h.available_quantity)} / {formatQty(h.total_quantity)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPrice(h.avg_entry_price)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPrice(h.mtm_price)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatINR(h.market_value)}</td>
                    <td
                      className={`px-3 py-1.5 text-right font-semibold tabular-nums ${
                        upnl > 0.01 ? "text-terminal-bid" : upnl < -0.01 ? "text-terminal-ask" : "text-slate-400"
                      }`}
                    >
                      {formatSignedINR(upnl)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {tab === "SHORTS" && (
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-3 py-1.5">Symbol</th>
                <th className="px-3 py-1.5 text-right">Borrowed Sh</th>
                <th className="px-3 py-1.5 text-right">Avg Short Px</th>
                <th className="px-3 py-1.5 text-right">MTM Liability</th>
                <th className="px-3 py-1.5 text-right">Margin Ratio</th>
                <th className="px-3 py-1.5">Health</th>
                <th className="px-3 py-1.5 text-right">Quick Cover</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {activeShorts.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-terminal-muted font-sans">
                    No open short liabilities. Borrowed shares appear here with real-time margin tracking.
                  </td>
                </tr>
              ) : (
                activeShorts.map((sp) => {
                  const mr = sp.margin_ratio !== null ? (toNum(sp.margin_ratio, 0) * 100).toFixed(1) + "%" : "—";
                  return (
                    <tr key={sp.symbol} className="hover:bg-white/[0.02]">
                      <td className="px-3 py-1.5 font-bold text-terminal-orange">{sp.symbol}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatQty(sp.borrowed_quantity)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatPrice(sp.avg_short_price)}</td>
                      <td className="px-3 py-1.5 text-right text-rose-300 tabular-nums">
                        {formatINR(sp.short_liability)}
                      </td>
                      <td className="px-3 py-1.5 text-right font-bold tabular-nums">{mr}</td>
                      <td className="px-3 py-1.5">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                            sp.margin_status === "HEALTHY"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : sp.margin_status === "WARNING"
                              ? "bg-amber-500/15 text-amber-300"
                              : "bg-rose-500/20 text-rose-300 animate-pulse"
                          }`}
                        >
                          {sp.margin_status}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-right">
                        <button
                          onClick={() => {
                            setSelectedSymbol(sp.symbol);
                            setTicketFromBook(
                              sp.mtm_price,
                              "BUY_TO_COVER",
                              Math.max(1, sp.borrowed_quantity - sp.reserved_cover_quantity)
                            );
                          }}
                          className="px-2 py-0.5 rounded bg-sky-500/20 border border-sky-500/40 text-sky-300 hover:bg-sky-500/30 font-bold text-[10px]"
                        >
                          COVER
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}

        {tab === "TRADES" && (
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-3 py-1.5">Time</th>
                <th className="px-3 py-1.5">Symbol</th>
                <th className="px-3 py-1.5">Side</th>
                <th className="px-3 py-1.5 text-right">Exec Px</th>
                <th className="px-3 py-1.5 text-right">Shares</th>
                <th className="px-3 py-1.5 text-right">Notional</th>
                <th className="px-3 py-1.5 text-right">Counterparty</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-terminal-muted font-sans">
                    No executed peer-to-peer fills yet.
                  </td>
                </tr>
              ) : (
                trades.slice(0, 25).map((tr) => (
                  <tr key={tr.trade_id} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-1.5 text-terminal-muted">
                      {new Date(tr.executed_at).toLocaleTimeString("en-IN", { hour12: false })}
                    </td>
                    <td className="px-3 py-1.5 font-bold text-white">{tr.symbol}</td>
                    <td className="px-3 py-1.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          tr.role === "BUYER"
                            ? "bg-emerald-500/15 text-emerald-300"
                            : "bg-rose-500/15 text-rose-300"
                        }`}
                      >
                        {tr.role}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatPrice(tr.price)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatQty(tr.quantity)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{formatINR(tr.notional)}</td>
                    <td className="px-3 py-1.5 text-right text-terminal-orange">{tr.counterparty_code}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
