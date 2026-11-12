"use client";

import React from "react";
import { formatPrice, formatSignedPct, toNum } from "@/lib/format";
import { useTerminalStore } from "@/store/terminalStore";

export function WatchlistPanel() {
  const stocks = useTerminalStore((s) => s.stocks);
  const selectedSymbol = useTerminalStore((s) => s.selectedSymbol);
  const setSelectedSymbol = useTerminalStore((s) => s.setSelectedSymbol);

  return (
    <div className="bg-terminal-panel border border-terminal-border rounded flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-terminal-border flex items-center justify-between bg-[#090D15]">
        <span className="text-xs font-bold uppercase tracking-wider text-white">
          MTT Market Watch (5)
        </span>
        <span className="text-[10px] font-mono text-terminal-muted">OPEN ₹1,000.00</span>
      </div>

      <div className="divide-y divide-terminal-border/60">
        {stocks.map((st) => {
          const active = st.symbol === selectedSymbol;
          const chg = toNum(st.change_pct_from_open, 0);
          return (
            <button
              key={st.symbol}
              type="button"
              onClick={() => setSelectedSymbol(st.symbol)}
              className={`w-full px-3 py-2.5 text-left transition flex items-center justify-between ${
                active
                  ? "bg-terminal-orange/10 border-l-2 border-l-terminal-orange"
                  : "hover:bg-white/[0.03]"
              }`}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono font-bold text-xs text-white">{st.symbol}</span>
                  <span className="text-[10px] text-terminal-muted truncate">{st.sector}</span>
                </div>
                <div className="text-[10px] font-mono text-terminal-muted mt-0.5">
                  BID {st.best_bid ? Number(st.best_bid).toFixed(2) : "—"} × ASK{" "}
                  {st.best_ask ? Number(st.best_ask).toFixed(2) : "—"}
                </div>
              </div>

              <div className="text-right font-mono shrink-0">
                <div className="text-xs font-bold text-white tabular-nums">
                  {formatPrice(st.last_traded_price || st.official_mtm_price)}
                </div>
                <div className="flex items-center justify-end gap-1.5 text-[10px] mt-0.5 tabular-nums">
                  <span className="text-terminal-orange" title="Fundamental Reference Price">
                    Ref {Number(st.fundamental_ref_price).toFixed(1)}
                  </span>
                  <span
                    className={`font-semibold ${
                      chg > 0.01
                        ? "text-terminal-bid"
                        : chg < -0.01
                        ? "text-terminal-ask"
                        : "text-slate-400"
                    }`}
                  >
                    {formatSignedPct(chg)}
                  </span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
