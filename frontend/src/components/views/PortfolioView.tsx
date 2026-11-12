"use client";

import React from "react";
import { ShieldCheck } from "lucide-react";
import { formatINR, formatPrice, formatQty, formatSignedINR, formatSignedPct, toNum } from "@/lib/format";
import { useTerminalStore } from "@/store/terminalStore";

export function PortfolioView() {
  const portfolio = useTerminalStore((s) => s.portfolio);
  const setSelectedSymbol = useTerminalStore((s) => s.setSelectedSymbol);
  const setActiveTab = useTerminalStore((s) => s.setActiveTab);

  if (!portfolio) {
    return (
      <div className="max-w-4xl mx-auto p-8 text-center text-sm text-terminal-muted">
        Portfolio ledger is available for seated tournament participants. Join the game from the
        Lobby or switch to a Player account.
      </div>
    );
  }

  const netWorth = toNum(portfolio.net_worth, 1000000);
  const totalPnl = netWorth - toNum(portfolio.starting_net_worth, 1000000);

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-4">
      {/* 4-Bucket Zero-Double-Counting Formula Breakdown */}
      <div className="bg-terminal-panel border border-terminal-border rounded-lg p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-terminal-orange" />
            <span className="text-xs font-bold uppercase tracking-wider text-white">
              Authoritative PostgreSQL Double-Entry Valuation (Zero Double-Counting Accounting)
            </span>
          </div>
          <span className="font-mono text-xs text-terminal-muted">
            Starting Net Worth: {formatINR(portfolio.starting_net_worth)}
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2 font-mono text-xs">
          <div className="bg-[#070A10] border border-terminal-border rounded p-2.5">
            <div className="text-[10px] text-terminal-muted">+ AVAIL CASH</div>
            <div className="font-bold text-white mt-0.5 tabular-nums">
              {formatINR(portfolio.available_cash)}
            </div>
          </div>
          <div className="bg-[#070A10] border border-terminal-border rounded p-2.5">
            <div className="text-[10px] text-terminal-muted">+ ORDER RES CASH</div>
            <div className="font-bold text-slate-200 mt-0.5 tabular-nums">
              {formatINR(portfolio.order_reserved_cash)}
            </div>
          </div>
          <div className="bg-[#070A10] border border-terminal-border rounded p-2.5">
            <div className="text-[10px] text-amber-300">+ SHORT PROCEEDS</div>
            <div className="font-bold text-amber-200 mt-0.5 tabular-nums">
              {formatINR(portfolio.short_proceeds_locked)}
            </div>
          </div>
          <div className="bg-[#070A10] border border-terminal-border rounded p-2.5">
            <div className="text-[10px] text-amber-300">+ SHORT MARGIN</div>
            <div className="font-bold text-amber-200 mt-0.5 tabular-nums">
              {formatINR(portfolio.short_margin_locked)}
            </div>
          </div>
          <div className="bg-[#070A10] border border-terminal-border rounded p-2.5">
            <div className="text-[10px] text-emerald-300">+ LONG MKT VALUE</div>
            <div className="font-bold text-emerald-300 mt-0.5 tabular-nums">
              {formatINR(portfolio.long_market_value)}
            </div>
          </div>
          <div className="bg-[#070A10] border border-terminal-border rounded p-2.5">
            <div className="text-[10px] text-rose-300">− SHORT LIABILITY</div>
            <div className="font-bold text-rose-300 mt-0.5 tabular-nums">
              {formatINR(portfolio.short_buyback_liability)}
            </div>
          </div>
          <div className="bg-[#070A10] border border-terminal-border rounded p-2.5">
            <div className="text-[10px] text-rose-400">− UNFUNDED DEBT</div>
            <div className="font-bold text-rose-400 mt-0.5 tabular-nums">
              {formatINR(portfolio.unfunded_settlement_debt)}
            </div>
          </div>
          <div className="bg-terminal-orange/15 border border-terminal-orange rounded p-2.5">
            <div className="text-[10px] text-terminal-orange font-bold">= NET WORTH</div>
            <div className="font-black text-white mt-0.5 tabular-nums">{formatINR(netWorth)}</div>
            <div
              className={`text-[10px] font-bold ${
                totalPnl >= 0 ? "text-emerald-300" : "text-rose-300"
              }`}
            >
              {formatSignedINR(totalPnl)} ({formatSignedPct(portfolio.total_return_pct)})
            </div>
          </div>
        </div>
      </div>

      {/* Long Holdings Table */}
      <div className="bg-terminal-panel border border-terminal-border rounded overflow-hidden">
        <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] flex justify-between items-center">
          <span className="text-xs font-bold uppercase tracking-wider text-white">
            Owned Long Stock Positions (Segregated from Borrowed Shares)
          </span>
          <span className="font-mono text-xs text-terminal-muted">
            Realized Trading P&amp;L: {formatSignedINR(portfolio.realized_pnl)}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-4 py-2">Symbol</th>
                <th className="px-4 py-2 text-right">Available Sh</th>
                <th className="px-4 py-2 text-right">Reserved Sell Sh</th>
                <th className="px-4 py-2 text-right">Total Owned</th>
                <th className="px-4 py-2 text-right">Avg Entry Px</th>
                <th className="px-4 py-2 text-right">Official MTM Px</th>
                <th className="px-4 py-2 text-right">Market Value</th>
                <th className="px-4 py-2 text-right">Unrealized P&amp;L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {portfolio.long_holdings.map((h) => {
                const upnl = toNum(h.unrealized_pnl, 0);
                return (
                  <tr
                    key={h.symbol}
                    onClick={() => {
                      setSelectedSymbol(h.symbol);
                      setActiveTab("TERMINAL");
                    }}
                    className="hover:bg-white/[0.02] cursor-pointer"
                  >
                    <td className="px-4 py-2 font-bold text-white">{h.symbol}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatQty(h.available_quantity)}</td>
                    <td className="px-4 py-2 text-right text-amber-300 tabular-nums">
                      {formatQty(h.reserved_sell_quantity)}
                    </td>
                    <td className="px-4 py-2 text-right font-bold tabular-nums">
                      {formatQty(h.total_quantity)}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatPrice(h.avg_entry_price)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatPrice(h.mtm_price)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatINR(h.market_value)}</td>
                    <td
                      className={`px-4 py-2 text-right font-bold tabular-nums ${
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
        </div>
      </div>

      {/* Short Positions & Margin Surveillance */}
      <div className="bg-terminal-panel border border-terminal-border rounded overflow-hidden">
        <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] text-xs font-bold uppercase tracking-wider text-white">
          Borrowed Short Liabilities, Collateral Lock &amp; Margin Health
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-4 py-2">Symbol</th>
                <th className="px-4 py-2 text-right">Borrowed Sh</th>
                <th className="px-4 py-2 text-right">Avg Short Px</th>
                <th className="px-4 py-2 text-right">Proceeds Locked</th>
                <th className="px-4 py-2 text-right">Margin Locked</th>
                <th className="px-4 py-2 text-right">Buyback Liability</th>
                <th className="px-4 py-2 text-right">Unrealized P&amp;L</th>
                <th className="px-4 py-2 text-right">Margin Ratio</th>
                <th className="px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {portfolio.short_positions.filter((sp) => sp.borrowed_quantity > 0).length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-6 text-center text-terminal-muted font-sans">
                    Zero open short positions.
                  </td>
                </tr>
              ) : (
                portfolio.short_positions
                  .filter((sp) => sp.borrowed_quantity > 0)
                  .map((sp) => {
                    const upnl = toNum(sp.unrealized_pnl, 0);
                    return (
                      <tr key={sp.symbol} className="hover:bg-white/[0.02]">
                        <td className="px-4 py-2 font-bold text-terminal-orange">{sp.symbol}</td>
                        <td className="px-4 py-2 text-right font-bold tabular-nums">
                          {formatQty(sp.borrowed_quantity)}
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums">
                          {formatPrice(sp.avg_short_price)}
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums">
                          {formatINR(sp.sale_proceeds_locked)}
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums">
                          {formatINR(sp.margin_collateral_locked)}
                        </td>
                        <td className="px-4 py-2 text-right text-rose-300 tabular-nums">
                          {formatINR(sp.short_liability)}
                        </td>
                        <td
                          className={`px-4 py-2 text-right font-bold tabular-nums ${
                            upnl >= 0 ? "text-terminal-bid" : "text-terminal-ask"
                          }`}
                        >
                          {formatSignedINR(upnl)}
                        </td>
                        <td className="px-4 py-2 text-right font-bold tabular-nums">
                          {sp.margin_ratio ? `${(toNum(sp.margin_ratio) * 100).toFixed(1)}%` : "—"}
                        </td>
                        <td className="px-4 py-2">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              sp.margin_status === "HEALTHY"
                                ? "bg-emerald-500/15 text-emerald-300"
                                : "bg-rose-500/20 text-rose-300"
                            }`}
                          >
                            {sp.margin_status}
                          </span>
                        </td>
                      </tr>
                    );
                  })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
