"use client";

import React from "react";
import { ArrowRight, CheckCircle2, Clock, ShieldCheck, Users } from "lucide-react";
import { formatCountdown, formatINR, formatQty, toNum } from "@/lib/format";
import { useAuthStore } from "@/store/authStore";
import { useTerminalStore } from "@/store/terminalStore";

export function LobbyView() {
  const user = useAuthStore((s) => s.user);
  const activeGame = useTerminalStore((s) => s.activeGame);
  const clock = useTerminalStore((s) => s.clock);
  const stocks = useTerminalStore((s) => s.stocks);
  const joinActiveGame = useTerminalStore((s) => s.joinActiveGame);
  const setActiveTab = useTerminalStore((s) => s.setActiveTab);

  if (!activeGame) return null;

  const startCash = toNum(activeGame.starting_cash, 500000);
  const startShares = activeGame.starting_shares_per_stock || 100;
  const startStockVal = startShares * 5 * 1000;

  return (
    <div className="max-w-6xl mx-auto p-4 space-y-4">
      <div className="bg-terminal-panel border border-terminal-border rounded-lg p-6 flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded bg-terminal-orange/15 border border-terminal-orange/40 text-terminal-orange font-mono text-xs font-bold">
            CODE: {activeGame.code} • STATUS: {activeGame.status}
          </div>
          <h1 className="text-2xl font-bold text-white">{activeGame.name}</h1>
          <p className="text-xs text-terminal-muted max-w-2xl leading-relaxed">
            Official Round 1 simulation of the Mumbai Trading Tournament organized by Quantrelic
            Analytics. All executions occur strictly peer-to-peer on the central Continuous Double
            Auction order book with zero artificial market makers.
          </p>
          <div className="flex flex-wrap items-center gap-4 pt-1 text-xs font-mono text-slate-300">
            <span className="inline-flex items-center gap-1.5">
              <Users className="w-4 h-4 text-terminal-orange" />
              {activeGame.participant_count ?? 0} Seated Competitors
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock className="w-4 h-4 text-emerald-400" />
              Phase A: {Math.round(activeGame.trading_duration_sec / 60)}m Main Trading + Phase B:{" "}
              {Math.round(activeGame.settlement_duration_sec / 60)}m Short Settlement
            </span>
          </div>
        </div>

        <div className="flex flex-col items-stretch sm:items-end gap-2 shrink-0 w-full sm:w-auto">
          {user?.role === "PLAYER" && !activeGame.joined ? (
            <button
              onClick={joinActiveGame}
              className="px-5 py-3 rounded bg-terminal-orange hover:bg-terminal-orangeHover text-black font-mono font-black text-xs uppercase tracking-wider flex items-center justify-center gap-2 shadow-lg"
            >
              Initialize Seat &amp; Claim ₹10,00,000 Allocation
              <ArrowRight className="w-4 h-4" />
            </button>
          ) : (
            <div className="space-y-2 text-right">
              {activeGame.joined && (
                <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs font-mono">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  SEAT INITIALIZED ({activeGame.tournament_code})
                </div>
              )}
              <div>
                <button
                  onClick={() => setActiveTab("TERMINAL")}
                  className="px-5 py-2.5 rounded bg-terminal-orange hover:bg-terminal-orangeHover text-black font-mono font-bold text-xs uppercase tracking-wider inline-flex items-center gap-2"
                >
                  Enter Live Trading Floor
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
          {clock && (clock.status === "MAIN_TRADING" || clock.status === "SHORT_SETTLEMENT") && (
            <div className="text-xs font-mono text-terminal-muted">
              Phase Remaining: <strong className="text-white">{formatCountdown(clock.remaining_phase_sec)}</strong>
            </div>
          )}
        </div>
      </div>

      {/* Allocation & Exchange Rules Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-terminal-panel border border-terminal-border rounded p-4 space-y-3">
          <div className="text-xs font-bold uppercase tracking-wider text-terminal-orange flex items-center gap-1.5">
            <ShieldCheck className="w-4 h-4" />
            1. Atomic Starting Allocation
          </div>
          <div className="space-y-1.5 font-mono text-xs">
            <div className="flex justify-between">
              <span className="text-terminal-muted">Opening Stock Price (All 5):</span>
              <span className="text-white font-bold">₹1,000.00</span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Initial Shares / Company:</span>
              <span className="text-white font-bold">{formatQty(startShares)} sh (Integer Only)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Initial Equity Value (5×100):</span>
              <span className="text-emerald-300 font-bold">{formatINR(startStockVal)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Initial Available Cash:</span>
              <span className="text-emerald-300 font-bold">{formatINR(startCash)}</span>
            </div>
            <div className="pt-2 border-t border-terminal-border flex justify-between text-sm">
              <span className="text-white font-bold">Starting Net Worth:</span>
              <span className="text-terminal-orange font-black">
                {formatINR(startCash + startStockVal)}
              </span>
            </div>
          </div>
        </div>

        <div className="bg-terminal-panel border border-terminal-border rounded p-4 space-y-3">
          <div className="text-xs font-bold uppercase tracking-wider text-terminal-orange">
            2. Short-Selling &amp; Margin Rules
          </div>
          <div className="space-y-1.5 font-mono text-xs">
            <div className="flex justify-between">
              <span className="text-terminal-muted">Central Borrow Pool / Stock:</span>
              <span className="text-white">{formatQty(activeGame.default_short_pool_shares)} sh</span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Max Player Short / Stock:</span>
              <span className="text-white">{formatQty(activeGame.short_position_limit_per_stock)} sh</span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Initial Margin Requirement:</span>
              <span className="text-amber-300 font-bold">
                {(toNum(activeGame.initial_margin_ratio) * 100).toFixed(0)}%
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Maintenance Margin Ratio:</span>
              <span className="text-rose-300 font-bold">
                {(toNum(activeGame.maintenance_margin_ratio) * 100).toFixed(0)}% ({activeGame.margin_call_grace_sec}s grace)
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-terminal-muted">Sale Proceeds Treatment:</span>
              <span className="text-slate-300">Segregated Collateral (Zero Double-Count)</span>
            </div>
          </div>
        </div>

        <div className="bg-terminal-panel border border-terminal-border rounded p-4 space-y-3">
          <div className="text-xs font-bold uppercase tracking-wider text-terminal-orange">
            3. Two-Phase Server Clock &amp; Settlement
          </div>
          <ul className="text-xs text-slate-300 space-y-1.5 leading-relaxed">
            <li>
              • <strong>Phase A (45m):</strong> Full peer-to-peer Market &amp; Limit orders, Short Selling,
              and live simulated Breaking News shocks.
            </li>
            <li>
              • <strong>Phase B (5m Settlement):</strong> Close-only window! Only{" "}
              <code className="font-mono text-sky-300">BUY_TO_COVER</code> and{" "}
              <code className="font-mono text-rose-300">SELL_LONG</code> allowed; resting opening orders are
              automatically cancelled.
            </li>
            <li>
              • <strong>End of Game (00:00):</strong> Unsettled shorts are liquidated at Official Final
              Settlement Price; unpaid shortfalls record negative debt without silent waiver.
            </li>
          </ul>
        </div>
      </div>

      {/* 5 Simulated Equities Table */}
      <div className="bg-terminal-panel border border-terminal-border rounded overflow-hidden">
        <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] text-xs font-bold uppercase tracking-wider text-white">
          Simulated Tournament Universe (5 Indian Companies • Rebased at ₹1,000.00)
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-4 py-2">Symbol</th>
                <th className="px-4 py-2 font-sans">Company Name</th>
                <th className="px-4 py-2 font-sans">Sector</th>
                <th className="px-4 py-2 text-right">Opening Px</th>
                <th className="px-4 py-2 text-right">Live Ref Px</th>
                <th className="px-4 py-2 text-right">Borrow Pool Rem</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {stocks.map((st) => (
                <tr key={st.symbol} className="hover:bg-white/[0.02]">
                  <td className="px-4 py-2 font-bold text-terminal-orange">{st.symbol}</td>
                  <td className="px-4 py-2 font-sans text-white">{st.company_name}</td>
                  <td className="px-4 py-2 font-sans text-terminal-muted">{st.sector}</td>
                  <td className="px-4 py-2 text-right">₹1,000.00</td>
                  <td className="px-4 py-2 text-right text-emerald-300">
                    ₹{Number(st.fundamental_ref_price).toFixed(2)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {formatQty(st.borrow_pool?.remaining_shares ?? 0)} /{" "}
                    {formatQty(st.borrow_pool?.total_pool_shares ?? 0)} sh
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
