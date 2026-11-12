"use client";

import React from "react";
import { Award, Lock, Trophy } from "lucide-react";
import { formatINR, formatSignedINR, formatSignedPct, toNum } from "@/lib/format";
import { useAuthStore } from "@/store/authStore";
import { useTerminalStore } from "@/store/terminalStore";

export function LeaderboardView() {
  const user = useAuthStore((s) => s.user);
  const activeGame = useTerminalStore((s) => s.activeGame);
  const leaderboard = useTerminalStore((s) => s.leaderboard);

  const isCompleted = activeGame?.status === "COMPLETED";

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-4">
      <div className="bg-terminal-panel border border-terminal-border rounded-lg p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Trophy className="w-5 h-5 text-terminal-orange" />
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              {isCompleted
                ? "Official Final Championship Standings (Locked)"
                : "Live Tournament Net Worth Standings"}
              {isCompleted && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-sky-500/20 border border-sky-500/40 text-sky-300 text-[10px] font-mono">
                  <Lock className="w-3 h-3" /> FINAL CERTIFIED
                </span>
              )}
            </h2>
            <p className="text-xs text-terminal-muted">
              Ranked by Net Worth = Cash + Reserved + Short Collateral + Long MTM − Short Liability −
              Unfunded Debt (Tie-Breaker: Higher Realized P&amp;L)
            </p>
          </div>
        </div>
      </div>

      {/* Top 3 Podium Cards */}
      {leaderboard.length >= 3 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {leaderboard.slice(0, 3).map((entry, idx) => (
            <div
              key={entry.game_participant_id}
              className={`rounded-lg p-4 border font-mono ${
                idx === 0
                  ? "bg-terminal-orange/10 border-terminal-orange shadow-[0_0_25px_rgba(255,107,0,0.12)]"
                  : "bg-terminal-panel border-terminal-border"
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="inline-flex items-center gap-1 text-xs font-bold text-terminal-orange">
                  <Award className="w-4 h-4" /> RANK #{entry.rank}
                </span>
                <span className="text-[11px] text-terminal-muted">{entry.tournament_code}</span>
              </div>
              <div className="font-sans text-base font-bold text-white">{entry.display_name}</div>
              <div className="font-sans text-[11px] text-terminal-muted mb-2">
                {entry.institution || entry.username}
              </div>
              <div className="text-lg font-black text-white tabular-nums">
                {formatINR(entry.net_worth)}
              </div>
              <div
                className={`text-xs font-bold tabular-nums ${
                  toNum(entry.return_pct) >= 0 ? "text-terminal-bid" : "text-terminal-ask"
                }`}
              >
                {formatSignedPct(entry.return_pct)} • Realized {formatSignedINR(entry.realized_pnl)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Full Standings Table */}
      <div className="bg-terminal-panel border border-terminal-border rounded overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-xs">
            <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
              <tr>
                <th className="px-4 py-2.5">Rank</th>
                <th className="px-4 py-2.5">Seat</th>
                <th className="px-4 py-2.5 font-sans">Participant</th>
                <th className="px-4 py-2.5 text-right">Net Worth</th>
                <th className="px-4 py-2.5 text-right">Return %</th>
                <th className="px-4 py-2.5 text-right">Realized P&amp;L</th>
                <th className="px-4 py-2.5 text-right">Long Value</th>
                <th className="px-4 py-2.5 text-right">Short Liability</th>
                <th className="px-4 py-2.5 text-right">Unfunded Debt</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-terminal-border/50">
              {leaderboard.map((row) => {
                const isMe = user?.username === row.username;
                const ret = toNum(row.return_pct, 0);
                return (
                  <tr
                    key={row.game_participant_id}
                    className={
                      isMe
                        ? "bg-terminal-orange/15 border-l-2 border-l-terminal-orange"
                        : "hover:bg-white/[0.02]"
                    }
                  >
                    <td className="px-4 py-2 font-black text-white">#{row.rank}</td>
                    <td className="px-4 py-2 text-terminal-orange">{row.tournament_code}</td>
                    <td className="px-4 py-2 font-sans">
                      <div className="font-semibold text-white">
                        {row.display_name}{" "}
                        {isMe && (
                          <span className="ml-1 px-1.5 py-0.5 rounded bg-terminal-orange text-black text-[9px] font-mono font-bold">
                            YOU
                          </span>
                        )}
                      </div>
                      {row.institution && (
                        <div className="text-[10px] text-terminal-muted">{row.institution}</div>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right font-bold text-white tabular-nums">
                      {formatINR(row.net_worth)}
                    </td>
                    <td
                      className={`px-4 py-2 text-right font-bold tabular-nums ${
                        ret > 0.01 ? "text-terminal-bid" : ret < -0.01 ? "text-terminal-ask" : "text-slate-400"
                      }`}
                    >
                      {formatSignedPct(ret)}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {formatSignedINR(row.realized_pnl)}
                    </td>
                    <td className="px-4 py-2 text-right text-emerald-300 tabular-nums">
                      {formatINR(row.long_market_value)}
                    </td>
                    <td className="px-4 py-2 text-right text-rose-300 tabular-nums">
                      {formatINR(row.short_liability)}
                    </td>
                    <td className="px-4 py-2 text-right text-rose-400 tabular-nums">
                      {toNum(row.unfunded_debt) > 0 ? formatINR(row.unfunded_debt) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
