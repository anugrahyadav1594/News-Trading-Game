"use client";

import React from "react";
import { CandlestickChart } from "@/components/CandlestickChart";
import { NewsWirePanel } from "@/components/NewsWirePanel";
import { OrderBookLadder } from "@/components/OrderBookLadder";
import { OrderTicket } from "@/components/OrderTicket";
import { formatQty } from "@/lib/format";
import { useTerminalStore } from "@/store/terminalStore";

const FACTOR_LABELS: Record<string, string> = {
  repo_rate: "RBI Repo Rate / Tightening",
  inr_usd: "INR Depreciation (USD Strength)",
  crude_oil: "Global Crude Oil Benchmark",
  india_gdp: "Domestic GDP & Credit Growth",
  global_it_spend: "Global Enterprise Tech Spend",
  usfda_regulatory: "USFDA / Pharma Export Clearance",
  ev_subsidy: "EV / Auto Policy & Demand",
  fiscal_capex: "Govt Infrastructure Capex",
  inflation_cpi: "CPI Input Cost Inflation",
  geopolitical_risk: "Global Geopolitical Shock",
};

export function StockDetailView() {
  const stocks = useTerminalStore((s) => s.stocks);
  const selectedSymbol = useTerminalStore((s) => s.selectedSymbol);
  const setSelectedSymbol = useTerminalStore((s) => s.setSelectedSymbol);

  const stock = stocks.find((s) => s.symbol === selectedSymbol);
  const profile = stock?.exposure_profile || {};
  const pool = stock?.borrow_pool;
  const poolUsedPct =
    pool && pool.total_pool_shares > 0
      ? ((pool.total_pool_shares - pool.remaining_shares) / pool.total_pool_shares) * 100
      : 0;

  return (
    <div className="p-3 space-y-3">
      {/* Stock Selector Bar */}
      <div className="flex flex-wrap items-center gap-2">
        {stocks.map((st) => (
          <button
            key={st.symbol}
            onClick={() => setSelectedSymbol(st.symbol)}
            className={`px-3 py-1.5 rounded border font-mono text-xs font-bold transition ${
              st.symbol === selectedSymbol
                ? "bg-terminal-orange text-black border-terminal-orange"
                : "bg-terminal-panel border-terminal-border text-slate-300 hover:border-slate-500"
            }`}
          >
            {st.symbol} • ₹{Number(st.last_traded_price || st.official_mtm_price).toFixed(2)}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-3">
        {/* Left/Center 8 Cols: Deep Chart + Factor Sensitivity Matrix + Company Wire */}
        <div className="xl:col-span-8 space-y-3">
          <CandlestickChart height={380} />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {/* Structured Factor Sensitivity Profile */}
            <div className="bg-terminal-panel border border-terminal-border rounded p-3.5 space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wider text-white">
                  Macro &amp; Sector Factor Sensitivities ({selectedSymbol})
                </span>
                <span className="text-[10px] font-mono text-terminal-muted">-1.0 TO +1.0 BETA</span>
              </div>
              <div className="space-y-1.5">
                {Object.entries(FACTOR_LABELS).map(([key, label]) => {
                  const val = Number(profile[key] ?? 0);
                  const widthPct = Math.min(100, Math.abs(val) * 100);
                  return (
                    <div key={key} className="text-[11px]">
                      <div className="flex justify-between font-mono mb-0.5">
                        <span className="text-slate-300 font-sans">{label}</span>
                        <span
                          className={
                            val > 0.05
                              ? "text-terminal-bid font-bold"
                              : val < -0.05
                              ? "text-terminal-ask font-bold"
                              : "text-terminal-muted"
                          }
                        >
                          {val > 0 ? `+${val.toFixed(2)}` : val.toFixed(2)}
                        </span>
                      </div>
                      <div className="h-1.5 bg-[#070A10] rounded overflow-hidden">
                        <div
                          className={`h-full ${val >= 0 ? "bg-emerald-500" : "bg-rose-500"}`}
                          style={{ width: `${widthPct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Short-Borrow Pool & Company News */}
            <div className="space-y-3">
              <div className="bg-terminal-panel border border-terminal-border rounded p-3.5 space-y-2">
                <div className="text-xs font-bold uppercase tracking-wider text-white">
                  Central Stock-Borrowing Pool ({selectedSymbol})
                </div>
                <div className="grid grid-cols-3 gap-2 font-mono text-xs">
                  <div className="bg-[#070A10] p-2 rounded border border-terminal-border">
                    <div className="text-[10px] text-terminal-muted">TOTAL POOL</div>
                    <div className="font-bold text-white">{formatQty(pool?.total_pool_shares ?? 0)}</div>
                  </div>
                  <div className="bg-[#070A10] p-2 rounded border border-terminal-border">
                    <div className="text-[10px] text-terminal-muted">BORROWED</div>
                    <div className="font-bold text-amber-300">{formatQty(pool?.borrowed_shares ?? 0)}</div>
                  </div>
                  <div className="bg-[#070A10] p-2 rounded border border-terminal-border">
                    <div className="text-[10px] text-terminal-muted">AVAILABLE</div>
                    <div className="font-bold text-emerald-300">{formatQty(pool?.remaining_shares ?? 0)}</div>
                  </div>
                </div>
                <div className="h-2 bg-[#070A10] rounded overflow-hidden border border-terminal-border">
                  <div
                    className="h-full bg-terminal-orange transition-all"
                    style={{ width: `${Math.min(100, poolUsedPct)}%` }}
                  />
                </div>
                <div className="text-[10px] font-mono text-terminal-muted flex justify-between">
                  <span>Pool Utilization: {poolUsedPct.toFixed(1)}%</span>
                  <span>Player Short Cap: {formatQty(stock?.short_position_limit ?? 500)} sh</span>
                </div>
              </div>

              <NewsWirePanel filterSymbol={selectedSymbol} maxHeightClass="max-h-[250px]" />
            </div>
          </div>
        </div>

        {/* Right 4 Cols: L2 Order Book + Order Ticket */}
        <div className="xl:col-span-4 space-y-3">
          <OrderBookLadder />
          <OrderTicket />
        </div>
      </div>
    </div>
  );
}
