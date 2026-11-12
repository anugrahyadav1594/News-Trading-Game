"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  BarChart3,
  Clock,
  History,
  LayoutGrid,
  Lock,
  LogOut,
  Shield,
  Trophy,
  Wallet,
} from "lucide-react";
import {
  formatCountdown,
  formatINR,
  formatSignedINR,
  formatSignedPct,
  toNum,
} from "@/lib/format";
import { useAuthStore } from "@/store/authStore";
import { type PlayerTab, useTerminalStore } from "@/store/terminalStore";

const NAV_ITEMS: Array<{ id: PlayerTab; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { id: "LOBBY", label: "Lobby", icon: LayoutGrid },
  { id: "TERMINAL", label: "Trading Floor", icon: Activity },
  { id: "STOCK_DETAIL", label: "Stock Profile", icon: BarChart3 },
  { id: "PORTFOLIO", label: "Portfolio & Risk", icon: Wallet },
  { id: "HISTORY", label: "Orders & Fills", icon: History },
  { id: "LEADERBOARD", label: "Leaderboard", icon: Trophy },
];

export function TopCommandBar() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const games = useTerminalStore((s) => s.games);
  const activeGame = useTerminalStore((s) => s.activeGame);
  const clock = useTerminalStore((s) => s.clock);
  const portfolio = useTerminalStore((s) => s.portfolio);
  const activeTab = useTerminalStore((s) => s.activeTab);
  const setActiveTab = useTerminalStore((s) => s.setActiveTab);
  const selectGame = useTerminalStore((s) => s.selectGame);
  const disconnectStream = useTerminalStore((s) => s.disconnectStream);

  const [displaySec, setDisplaySec] = useState<number>(clock?.remaining_phase_sec ?? 0);

  useEffect(() => {
    setDisplaySec(clock?.remaining_phase_sec ?? 0);
  }, [clock?.remaining_phase_sec, clock?.server_time, clock?.status]);

  useEffect(() => {
    if (!clock) return;
    if (clock.status !== "MAIN_TRADING" && clock.status !== "SHORT_SETTLEMENT") return;
    const t = setInterval(() => {
      setDisplaySec((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(t);
  }, [clock?.status]);

  const netWorth = toNum(portfolio?.net_worth, 1000000);
  const netPnl = netWorth - toNum(portfolio?.starting_net_worth, 1000000);
  const retPct = toNum(portfolio?.total_return_pct, 0);
  const unfundedDebt = toNum(portfolio?.unfunded_settlement_debt, 0);

  const phaseBadge = (() => {
    const st = clock?.status || activeGame?.status || "LOBBY";
    if (st === "MAIN_TRADING") {
      return {
        label: "PHASE A • MAIN TRADING",
        cls: "bg-emerald-500/15 border-emerald-500/40 text-emerald-300",
        timerCls: "text-emerald-400",
      };
    }
    if (st === "SHORT_SETTLEMENT") {
      return {
        label: "PHASE B • SHORT SETTLEMENT ONLY",
        cls: "bg-terminal-orange/20 border-terminal-orange text-terminal-orange animate-pulse",
        timerCls: "text-terminal-orange",
      };
    }
    if (st === "PAUSED") {
      return {
        label: "CIRCUIT BREAKER • PAUSED",
        cls: "bg-amber-500/20 border-amber-500/50 text-amber-300",
        timerCls: "text-amber-300",
      };
    }
    if (st === "COMPLETED") {
      return {
        label: "COMPLETED • FINAL SETTLEMENT LOCKED",
        cls: "bg-sky-500/15 border-sky-500/40 text-sky-300",
        timerCls: "text-sky-300",
      };
    }
    return {
      label: `PRE-GAME • ${st}`,
      cls: "bg-slate-700/40 border-slate-600 text-slate-300",
      timerCls: "text-slate-300",
    };
  })();

  return (
    <header className="bg-terminal-panel border-b border-terminal-border select-none">
      {/* Row 1: Brand + Game Switcher + Server Clock + Portfolio Strip + User */}
      <div className="px-3 py-2 flex flex-wrap items-center justify-between gap-3 border-b border-terminal-border/70">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded bg-terminal-orange flex items-center justify-center font-mono font-black text-black text-xs shadow-[0_0_15px_rgba(255,107,0,0.45)]">
              MTT
            </div>
            <div>
              <div className="text-sm font-bold tracking-wider text-white flex items-center gap-1.5">
                NEWS TRADING <span className="text-terminal-orange">— MTT</span>
              </div>
              <div className="text-[10px] text-terminal-muted uppercase tracking-widest">
                Peer-to-Peer Central Exchange
              </div>
            </div>
          </div>

          <div className="h-6 w-px bg-terminal-border mx-1 hidden sm:block" />

          {/* Active Tournament Selector */}
          <select
            aria-label="Select Tournament Game"
            value={activeGame?.game_id || ""}
            onChange={(e) => selectGame(e.target.value, true)}
            className="bg-terminal-elevated border border-terminal-borderBright text-xs text-white rounded px-2.5 py-1.5 font-mono focus:outline-none focus:border-terminal-orange"
          >
            {games.map((g) => (
              <option key={g.game_id} value={g.game_id}>
                [{g.code}] {g.name} ({g.status})
              </option>
            ))}
          </select>

          {/* Authoritative Server Phase & Countdown */}
          <div className={`flex items-center gap-2 px-2.5 py-1 rounded border text-xs ${phaseBadge.cls}`}>
            <Clock className="w-3.5 h-3.5" />
            <span className="font-semibold tracking-wider text-[11px]">{phaseBadge.label}</span>
            {(clock?.status === "MAIN_TRADING" || clock?.status === "SHORT_SETTLEMENT") && (
              <span className={`font-mono font-bold text-sm ml-1 tabular-nums ${phaseBadge.timerCls}`}>
                {formatCountdown(displaySec)}
              </span>
            )}
          </div>
        </div>

        {/* Portfolio Valuation Telemetry */}
        <div className="flex items-center gap-4 font-mono text-xs">
          {portfolio ? (
            <>
              <div>
                <div className="text-[10px] text-terminal-muted uppercase">Net Worth</div>
                <div className="font-bold text-white text-sm tabular-nums">{formatINR(netWorth)}</div>
              </div>
              <div>
                <div className="text-[10px] text-terminal-muted uppercase">Total P&amp;L</div>
                <div
                  className={`font-bold tabular-nums ${
                    netPnl > 0.01 ? "text-terminal-bid" : netPnl < -0.01 ? "text-terminal-ask" : "text-slate-300"
                  }`}
                >
                  {formatSignedINR(netPnl)} ({formatSignedPct(retPct)})
                </div>
              </div>
              <div className="hidden xl:block">
                <div className="text-[10px] text-terminal-muted uppercase">Avail Cash</div>
                <div className="text-slate-200 font-semibold tabular-nums">
                  {formatINR(portfolio.available_cash)}
                </div>
              </div>
              <div className="hidden 2xl:block">
                <div className="text-[10px] text-terminal-muted uppercase">Short Margin+Proc</div>
                <div className="text-amber-300 font-semibold tabular-nums">
                  {formatINR(
                    toNum(portfolio.short_margin_locked) + toNum(portfolio.short_proceeds_locked)
                  )}
                </div>
              </div>
              {unfundedDebt > 0 && (
                <div className="px-2 py-0.5 rounded bg-rose-500/20 border border-rose-500/50 text-rose-300">
                  <div className="text-[9px] uppercase">Unfunded Debt</div>
                  <div className="font-bold">{formatINR(unfundedDebt)}</div>
                </div>
              )}
            </>
          ) : (
            <div className="text-[11px] text-terminal-muted italic">
              {user?.role === "ADMIN" ? "Director Observer Mode" : "Join game in Lobby to initialize seat"}
            </div>
          )}

          <div className="h-6 w-px bg-terminal-border" />

          <div className="flex items-center gap-2 font-sans">
            {user?.role === "ADMIN" && (
              <Link
                href="/admin"
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-terminal-orange text-black font-bold text-xs hover:bg-terminal-orangeHover transition"
              >
                <Shield className="w-3.5 h-3.5" />
                Control Room
              </Link>
            )}
            <div className="text-right hidden md:block">
              <div className="text-xs font-semibold text-white leading-tight">
                {user?.display_name || user?.username}
              </div>
              <div className="text-[10px] text-terminal-orange font-mono">
                {activeGame?.tournament_code || user?.role}
              </div>
            </div>
            <button
              onClick={() => {
                disconnectStream();
                logout();
                router.push("/");
              }}
              title="Switch Account / Sign Out"
              className="p-1.5 rounded border border-terminal-border hover:border-terminal-orange text-terminal-muted hover:text-white transition"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Phase B or Completed Mandatory Operational Banner */}
      {clock?.status === "SHORT_SETTLEMENT" && (
        <div className="bg-terminal-orange/15 border-b border-terminal-orange/40 px-3 py-1.5 text-xs text-amber-200 flex items-center justify-between">
          <span>
            <strong className="text-terminal-orange uppercase">
              5-Minute Short Position Settlement Window Active:
            </strong>{" "}
            New Short Sales, New Speculative Long Purchases, and New Breaking News are LOCKED. Only{" "}
            <code className="font-mono bg-black/40 px-1 py-0.5 rounded text-emerald-300">BUY_TO_COVER</code>{" "}
            and <code className="font-mono bg-black/40 px-1 py-0.5 rounded text-rose-300">SELL_LONG</code>{" "}
            orders may be submitted. Any short positions still open at 00:00 will be automatically settled at
            the Official Final Settlement Price!
          </span>
        </div>
      )}

      {clock?.status === "COMPLETED" && (
        <div className="bg-sky-500/10 border-b border-sky-500/30 px-3 py-1.5 text-xs text-sky-200 flex items-center gap-2">
          <Lock className="w-3.5 h-3.5 text-sky-400 shrink-0" />
          <span>
            <strong>Tournament Concluded (Read-Only Final State):</strong> All remaining short obligations have
            been settled at Official Final Settlement Prices and official championship standings are locked.
          </span>
        </div>
      )}

      {/* Row 2: Player View Navigation Tabs */}
      <div className="px-3 flex items-center justify-between bg-[#080B12]">
        <nav className="flex items-center gap-1 overflow-x-auto">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold border-b-2 transition whitespace-nowrap ${
                  active
                    ? "border-terminal-orange text-terminal-orange bg-terminal-orange/5"
                    : "border-transparent text-terminal-muted hover:text-white hover:bg-white/[0.02]"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="hidden lg:flex items-center gap-3 text-[11px] text-terminal-muted font-mono">
          <span>UNIVERSE: 5 INDIAN LARGE-CAPS (SIMULATED ₹1,000 BASE)</span>
          <span>•</span>
          <span>MATCHING: P2P PRICE-TIME CDA</span>
        </div>
      </div>
    </header>
  );
}
