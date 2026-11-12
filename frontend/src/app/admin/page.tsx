"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  CheckCircle2,
  FileCheck2,
  Flame,
  Pause,
  Play,
  Plus,
  Radio,
  RefreshCw,
  RotateCcw,
  Shield,
  ShieldAlert,
  Sliders,
  Terminal,
  Trash2,
} from "lucide-react";
import { exchangeApi } from "@/lib/api";
import { formatCountdown, formatINR, formatPrice, formatQty, toNum } from "@/lib/format";
import { useAuthStore } from "@/store/authStore";
import type {
  AdminNewsEvent,
  AuditEntry,
  GameSummary,
  SurveillanceDashboard,
} from "@/types/exchange";

type AdminTab = "LIFECYCLE" | "NEWS_DESK" | "SURVEILLANCE" | "AUDIT";

export default function AdminControlRoomPage() {
  const router = useRouter();
  const { user, hydrated, hydrate, logout } = useAuthStore();

  const [tab, setTab] = useState<AdminTab>("SURVEILLANCE");
  const [games, setGames] = useState<GameSummary[]>([]);
  const [selectedGameId, setSelectedGameId] = useState<string>("");
  const [surveillance, setSurveillance] = useState<SurveillanceDashboard | null>(null);
  const [newsEvents, setNewsEvents] = useState<AdminNewsEvent[]>([]);
  const [categories, setCategories] = useState<
    Array<{ slug: string; name: string; is_builtin: boolean }>
  >([]);
  const [auditLogs, setAuditLogs] = useState<AuditEntry[]>([]);
  const [bannerMsg, setBannerMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  // Create Game State
  const [newGameCode, setNewGameCode] = useState("MTT-HEAT2");
  const [newGameName, setNewGameName] = useState("Mumbai Trading Tournament — Heat 2");
  const [newTradingSec, setNewTradingSec] = useState("2700");
  const [newSettleSec, setNewSettleSec] = useState("300");
  const [newPoolShares, setNewPoolShares] = useState("15000");
  const [newShortLimit, setNewShortLimit] = useState("500");
  const [newInitMargin, setNewInitMargin] = useState("0.50");
  const [newMaintMargin, setNewMaintMargin] = useState("0.25");

  // Emergency / Lifecycle Reason
  const [actionReason, setActionReason] = useState("Tournament Director operational command");

  // News Generator & Manual Event State
  const [batchCount, setBatchCount] = useState("15");
  const [batchIncludeChains, setBatchIncludeChains] = useState(true);
  const [batchAutoApprove, setBatchAutoApprove] = useState(true);
  const [newsStatusFilter, setNewsStatusFilter] = useState<string>("ALL");
  const [scheduleOffsetSec, setScheduleOffsetSec] = useState<string>("60");

  // Manual News Form
  const [manualHeadline, setManualHeadline] = useState("");
  const [manualBody, setManualBody] = useState("");
  const [manualCat, setManualCat] = useState("rbi_monetary_policy");
  const [manualSeverity, setManualSeverity] = useState("HIGH");
  const [manualSymbol, setManualSymbol] = useState("RELIANCE");
  const [manualDir, setManualDir] = useState<number>(1);
  const [manualMagPct, setManualMagPct] = useState("5.5");

  // Custom Category Form
  const [catSlug, setCatSlug] = useState("");
  const [catName, setCatName] = useState("");

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  const notify = (tone: "ok" | "err", text: string) => {
    setBannerMsg({ tone, text });
    setTimeout(() => setBannerMsg(null), 6000);
  };

  const loadGamesList = useCallback(async () => {
    const gRes = await exchangeApi.listGames();
    setGames(gRes.games);
    if (!selectedGameId && gRes.games.length > 0) {
      const live = gRes.games.find((g) => g.code === "MTT-ROUND1") || gRes.games[0];
      setSelectedGameId(live.game_id);
    }
  }, [selectedGameId]);

  const refreshAdminWorkspace = useCallback(async (gid: string) => {
    if (!gid) return;
    try {
      const [surv, nRes, cRes, aRes] = await Promise.all([
        exchangeApi.adminSurveillance(gid),
        exchangeApi.adminListNewsEvents(gid),
        exchangeApi.adminListCategories(),
        exchangeApi.adminAuditLogs(gid, 120),
      ]);
      setSurveillance(surv);
      setNewsEvents(nRes.events);
      setCategories(cRes.categories);
      setAuditLogs(aRes.audit_logs);
    } catch (err) {
      notify("err", err instanceof Error ? err.message : "Failed to load surveillance data");
    }
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (!user) {
      router.replace("/");
      return;
    }
    if (user.role !== "ADMIN") {
      router.replace("/terminal");
      return;
    }
    loadGamesList();
  }, [hydrated, user, router, loadGamesList]);

  useEffect(() => {
    if (!selectedGameId || user?.role !== "ADMIN") return;
    refreshAdminWorkspace(selectedGameId);
    const interval = setInterval(() => {
      refreshAdminWorkspace(selectedGameId);
    }, 3000);
    return () => clearInterval(interval);
  }, [selectedGameId, user?.role, refreshAdminWorkspace]);

  const runAction = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
      await loadGamesList();
      if (selectedGameId) await refreshAdminWorkspace(selectedGameId);
    } catch (err) {
      notify("err", err instanceof Error ? err.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  };

  const activeGame = games.find((g) => g.game_id === selectedGameId);

  if (!hydrated || !user || user.role !== "ADMIN") {
    return (
      <div className="min-h-screen bg-terminal-bg flex items-center justify-center font-mono text-xs text-terminal-muted">
        VERIFYING TOURNAMENT DIRECTOR CREDENTIALS...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-terminal-bg text-terminal-text flex flex-col">
      {/* Top Simulation & Control Room Header */}
      <div className="bg-[#0D131F] border-b border-terminal-border px-4 py-1.5 flex items-center justify-between text-[11px]">
        <div className="flex items-center gap-2 text-terminal-orange font-mono font-bold">
          <ShieldAlert className="w-3.5 h-3.5" />
          QUANTRELIC ANALYTICS • MTT TOURNAMENT DIRECTOR CONTROL ROOM (SIMULATED EXCHANGE)
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/terminal"
            className="inline-flex items-center gap-1 text-slate-300 hover:text-terminal-orange font-mono"
          >
            <Terminal className="w-3.5 h-3.5" />
            Observer Terminal View
          </Link>
          <button
            onClick={() => {
              logout();
              router.push("/");
            }}
            className="text-rose-300 hover:text-rose-200 font-mono"
          >
            Sign Out
          </button>
        </div>
      </div>

      {/* Command Bar */}
      <header className="bg-terminal-panel border-b border-terminal-border px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-terminal-orange text-black font-mono font-black flex items-center justify-center text-xs">
            DIR
          </div>
          <div>
            <h1 className="text-sm font-bold uppercase tracking-wider text-white">
              Exchange Governance &amp; Surveillance Console
            </h1>
            <div className="text-[11px] text-terminal-muted font-mono">
              Every administrative action writes a SHA-256 hash-chained PostgreSQL audit record
            </div>
          </div>

          <select
            aria-label="Select Game to Manage"
            value={selectedGameId}
            onChange={(e) => setSelectedGameId(e.target.value)}
            className="ml-2 bg-terminal-elevated border border-terminal-borderBright rounded px-3 py-1.5 text-xs font-mono text-white"
          >
            {games.map((g) => (
              <option key={g.game_id} value={g.game_id}>
                [{g.code}] {g.name} ({g.status})
              </option>
            ))}
          </select>
        </div>

        {/* Live Game Clock & Invariant Pill */}
        {surveillance && (
          <div className="flex items-center gap-3 font-mono text-xs">
            <div className="px-2.5 py-1 rounded bg-terminal-elevated border border-terminal-border">
              STATUS: <strong className="text-terminal-orange">{surveillance.status}</strong>{" "}
              {(surveillance.status === "MAIN_TRADING" ||
                surveillance.status === "SHORT_SETTLEMENT") && (
                <span className="ml-1 text-emerald-400 font-bold">
                  {formatCountdown(surveillance.clock.remaining_phase_sec)}
                </span>
              )}
            </div>
            <div
              className={`px-2.5 py-1 rounded border flex items-center gap-1.5 font-bold ${
                surveillance.invariants.passed
                  ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                  : "bg-rose-500/20 border-rose-500 text-rose-200 animate-pulse"
              }`}
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              {surveillance.invariants.passed
                ? `LEDGERS CONSERVED (${surveillance.invariants.participant_count} SEATS)`
                : `INVARIANT ALERT (${surveillance.invariants.violations.length})`}
            </div>
            <button
              onClick={() => refreshAdminWorkspace(selectedGameId)}
              className="p-1.5 rounded border border-terminal-border hover:border-terminal-orange text-terminal-muted hover:text-white"
              title="Refresh Now"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </header>

      {/* Module Navigation */}
      <div className="bg-[#080B12] border-b border-terminal-border px-4 flex items-center gap-2 overflow-x-auto">
        {(
          [
            { id: "SURVEILLANCE", label: "Live Exchange Surveillance", icon: Activity },
            { id: "NEWS_DESK", label: "News Generator & Release Desk", icon: Radio },
            { id: "LIFECYCLE", label: "Game Setup & Emergency Controls", icon: Sliders },
            { id: "AUDIT", label: "Immutable SHA-256 Audit Trail", icon: FileCheck2 },
          ] as const
        ).map((m) => {
          const Icon = m.icon;
          return (
            <button
              key={m.id}
              onClick={() => setTab(m.id)}
              className={`inline-flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-bold border-b-2 transition whitespace-nowrap ${
                tab === m.id
                  ? "border-terminal-orange text-terminal-orange bg-terminal-orange/5"
                  : "border-transparent text-terminal-muted hover:text-white"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {m.label}
            </button>
          );
        })}
      </div>

      {bannerMsg && (
        <div
          className={`mx-4 mt-3 px-4 py-2 rounded border text-xs font-mono ${
            bannerMsg.tone === "ok"
              ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-200"
              : "bg-rose-500/15 border-rose-500/40 text-rose-200"
          }`}
        >
          {bannerMsg.text}
        </div>
      )}

      <main className="flex-1 p-4 max-w-[1600px] w-full mx-auto space-y-4">
        {/* TAB 1: LIVE EXCHANGE SURVEILLANCE */}
        {tab === "SURVEILLANCE" && surveillance && (
          <div className="space-y-4">
            {/* Stock Books & Borrow Pools */}
            <div className="bg-terminal-panel border border-terminal-border rounded overflow-hidden">
              <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] text-xs font-bold uppercase tracking-wider text-white">
                5-Equity Market Microstructure &amp; Central Borrow Pool Telemetry
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left font-mono text-xs">
                  <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
                    <tr>
                      <th className="px-4 py-2">Symbol</th>
                      <th className="px-4 py-2 text-right">Last Traded</th>
                      <th className="px-4 py-2 text-right">Fundamental Ref</th>
                      <th className="px-4 py-2 text-right">Official MTM</th>
                      <th className="px-4 py-2 text-right">Best Bid × Ask</th>
                      <th className="px-4 py-2 text-right">Borrowed / Pool</th>
                      <th className="px-4 py-2 text-right">Pool Rem</th>
                      <th className="px-4 py-2 text-right">Open Orders</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-terminal-border/50">
                    {surveillance.stocks.map((st) => (
                      <tr key={st.symbol} className="hover:bg-white/[0.02]">
                        <td className="px-4 py-2 font-bold text-terminal-orange">{st.symbol}</td>
                        <td className="px-4 py-2 text-right text-white">
                          {st.ltp ? formatPrice(st.ltp) : "—"}
                        </td>
                        <td className="px-4 py-2 text-right text-amber-300">
                          {formatPrice(st.ref_price)}
                        </td>
                        <td className="px-4 py-2 text-right text-sky-300">
                          {formatPrice(st.mtm_price)}
                        </td>
                        <td className="px-4 py-2 text-right">
                          {st.best_bid ? Number(st.best_bid).toFixed(2) : "—"} ×{" "}
                          {st.best_ask ? Number(st.best_ask).toFixed(2) : "—"}
                        </td>
                        <td className="px-4 py-2 text-right">
                          {formatQty(st.pool_borrowed)} / {formatQty(st.pool_total)}
                        </td>
                        <td className="px-4 py-2 text-right text-emerald-300 font-bold">
                          {formatQty(st.pool_remaining)} sh
                        </td>
                        <td className="px-4 py-2 text-right">{st.open_orders}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
              {/* Participant Risk & Margin Surveillance */}
              <div className="xl:col-span-7 bg-terminal-panel border border-terminal-border rounded overflow-hidden">
                <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] text-xs font-bold uppercase tracking-wider text-white">
                  Participant Net Worth, Margin Exposure &amp; Solvency Matrix
                </div>
                <div className="overflow-x-auto max-h-[420px]">
                  <table className="w-full text-left font-mono text-xs">
                    <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
                      <tr>
                        <th className="px-3 py-2">Seat</th>
                        <th className="px-3 py-2 font-sans">Competitor</th>
                        <th className="px-3 py-2 text-right">Net Worth</th>
                        <th className="px-3 py-2 text-right">Avail Cash</th>
                        <th className="px-3 py-2 text-right">Short Liab</th>
                        <th className="px-3 py-2 text-right">Margin Calls</th>
                        <th className="px-3 py-2 text-right">Unfunded Debt</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-terminal-border/50">
                      {surveillance.participants.map((p) => (
                        <tr key={p.game_participant_id} className="hover:bg-white/[0.02]">
                          <td className="px-3 py-1.5 text-terminal-orange">{p.tournament_code}</td>
                          <td className="px-3 py-1.5 font-sans text-white font-semibold">
                            {p.display_name}
                          </td>
                          <td className="px-3 py-1.5 text-right font-bold text-white tabular-nums">
                            {formatINR(p.net_worth)}
                          </td>
                          <td className="px-3 py-1.5 text-right tabular-nums">
                            {formatINR(p.available_cash)}
                          </td>
                          <td className="px-3 py-1.5 text-right text-rose-300 tabular-nums">
                            {formatINR(p.short_liability)}
                          </td>
                          <td className="px-3 py-1.5 text-right">
                            {p.margin_call_positions > 0 ? (
                              <span className="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold">
                                {p.margin_call_positions} CALL
                              </span>
                            ) : (
                              <span className="text-emerald-400">OK</span>
                            )}
                          </td>
                          <td className="px-3 py-1.5 text-right text-rose-400">
                            {toNum(p.unfunded_debt) > 0 ? formatINR(p.unfunded_debt) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Full Non-Anonymized Surveillance Trade Tape */}
              <div className="xl:col-span-5 bg-terminal-panel border border-terminal-border rounded overflow-hidden">
                <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] text-xs font-bold uppercase tracking-wider text-white">
                  Full Non-Anonymized P2P Trade Tape (Anti-Collusion Feed)
                </div>
                <div className="overflow-x-auto max-h-[420px]">
                  <table className="w-full text-left font-mono text-xs">
                    <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
                      <tr>
                        <th className="px-3 py-2">Time</th>
                        <th className="px-3 py-2">Stock</th>
                        <th className="px-3 py-2 text-right">Px × Qty</th>
                        <th className="px-3 py-2">Buyer ↔ Seller</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-terminal-border/50">
                      {surveillance.recent_trades.map((tr) => (
                        <tr key={tr.trade_id} className="hover:bg-white/[0.02]">
                          <td className="px-3 py-1.5 text-terminal-muted">
                            {new Date(tr.executed_at).toLocaleTimeString("en-IN", { hour12: false })}
                          </td>
                          <td className="px-3 py-1.5 font-bold text-white">{tr.symbol}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">
                            ₹{Number(tr.price).toFixed(2)} × {tr.quantity}
                          </td>
                          <td className="px-3 py-1.5 text-[11px]">
                            <span className="text-emerald-300">{tr.buyer_username}</span>
                            <span className="text-terminal-muted"> ↔ </span>
                            <span className="text-rose-300">{tr.seller_username}</span>
                            {tr.is_forced && (
                              <span className="ml-1 px-1 rounded bg-rose-500/20 text-rose-300 text-[9px]">
                                LIQ
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: NEWS GENERATOR, EDITORIAL APPROVAL & BREAKING RELEASE CONSOLE */}
        {tab === "NEWS_DESK" && (
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
            {/* Left 4 Cols: Batch Generator + Manual Shock Composer + Custom Category */}
            <div className="xl:col-span-4 space-y-4 text-xs">
              {/* Batch Generator */}
              <div className="bg-terminal-panel border border-terminal-border rounded p-4 space-y-3">
                <div className="font-bold uppercase tracking-wider text-terminal-orange flex items-center gap-1.5">
                  <Flame className="w-4 h-4" />
                  1. Parameter-First Scenario Batch Generator
                </div>
                <p className="text-terminal-muted leading-relaxed">
                  Generates deterministic multi-factor news scenarios and 3-stage narrative chains
                  across the 25+ tournament categories with zero runtime LLM dependency.
                </p>
                <div className="grid grid-cols-2 gap-2 font-mono">
                  <div>
                    <label className="block text-[10px] text-terminal-muted mb-1">EVENT COUNT</label>
                    <input
                      type="number"
                      min={3}
                      max={100}
                      value={batchCount}
                      onChange={(e) => setBatchCount(e.target.value)}
                      className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                    />
                  </div>
                  <div className="flex flex-col justify-end gap-1.5 font-sans">
                    <label className="inline-flex items-center gap-1.5 text-slate-300">
                      <input
                        type="checkbox"
                        checked={batchIncludeChains}
                        onChange={(e) => setBatchIncludeChains(e.target.checked)}
                      />
                      Include 3-Stage Chains
                    </label>
                    <label className="inline-flex items-center gap-1.5 text-slate-300">
                      <input
                        type="checkbox"
                        checked={batchAutoApprove}
                        onChange={(e) => setBatchAutoApprove(e.target.checked)}
                      />
                      Auto-Approve Queue
                    </label>
                  </div>
                </div>
                <button
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      const res = await exchangeApi.adminGenerateNewsBatch(selectedGameId, {
                        count: Math.trunc(toNum(batchCount, 15)),
                        include_chains: batchIncludeChains,
                        auto_approve: batchAutoApprove,
                      });
                      notify("ok", `Generated ${res.generated_count} structured scenarios.`);
                    })
                  }
                  className="w-full py-2 rounded bg-terminal-orange hover:bg-terminal-orangeHover text-black font-mono font-bold uppercase"
                >
                  Generate Structured News Batch
                </button>
              </div>

              {/* Manual Structured News Shock Composer */}
              <div className="bg-terminal-panel border border-terminal-border rounded p-4 space-y-2.5">
                <div className="font-bold uppercase tracking-wider text-white">
                  2. Compose Custom Breaking Event
                </div>
                <input
                  type="text"
                  placeholder="[SIMULATED] Headline (min 10 chars)..."
                  value={manualHeadline}
                  onChange={(e) => setManualHeadline(e.target.value)}
                  className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                />
                <textarea
                  rows={3}
                  placeholder="Detailed simulated tournament story body (min 20 chars)..."
                  value={manualBody}
                  onChange={(e) => setManualBody(e.target.value)}
                  className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                />
                <div className="grid grid-cols-2 gap-2 font-mono">
                  <select
                    value={manualCat}
                    onChange={(e) => setManualCat(e.target.value)}
                    className="bg-[#070A10] border border-terminal-border rounded px-2 py-1.5 text-white text-[11px]"
                  >
                    {categories.map((c) => (
                      <option key={c.slug} value={c.slug}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  <select
                    value={manualSeverity}
                    onChange={(e) => setManualSeverity(e.target.value)}
                    className="bg-[#070A10] border border-terminal-border rounded px-2 py-1.5 text-white text-[11px]"
                  >
                    {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((sv) => (
                      <option key={sv} value={sv}>
                        {sv}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="grid grid-cols-3 gap-2 font-mono">
                  <select
                    value={manualSymbol}
                    onChange={(e) => setManualSymbol(e.target.value)}
                    className="bg-[#070A10] border border-terminal-border rounded px-2 py-1.5 text-white text-[11px]"
                  >
                    {["RELIANCE", "ICICIBANK", "TATAMOTORS", "SUNPHARMA", "INFY"].map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                  <select
                    value={manualDir}
                    onChange={(e) => setManualDir(Number(e.target.value))}
                    className="bg-[#070A10] border border-terminal-border rounded px-2 py-1.5 text-white text-[11px]"
                  >
                    <option value={1}>BULLISH (+1)</option>
                    <option value={-1}>BEARISH (-1)</option>
                  </select>
                  <input
                    type="number"
                    step={0.5}
                    min={0.5}
                    max={30}
                    value={manualMagPct}
                    onChange={(e) => setManualMagPct(e.target.value)}
                    className="bg-[#070A10] border border-terminal-border rounded px-2 py-1.5 text-white text-[11px]"
                    title="Magnitude %"
                  />
                </div>
                <button
                  disabled={busy || manualHeadline.length < 10 || manualBody.length < 20}
                  onClick={() =>
                    runAction(async () => {
                      const sevNum =
                        manualSeverity === "CRITICAL"
                          ? "0.95"
                          : manualSeverity === "HIGH"
                          ? "0.75"
                          : manualSeverity === "MEDIUM"
                          ? "0.50"
                          : "0.30";
                      await exchangeApi.adminCreateManualNews(selectedGameId, {
                        category: manualCat || categories[0]?.slug || "MONETARY_POLICY",
                        news_type: "BREAKING",
                        headline: manualHeadline,
                        body: manualBody,
                        primary_symbol: manualSymbol,
                        direction: manualDir >= 0 ? "POSITIVE" : "NEGATIVE",
                        severity: sevNum,
                        credibility: "0.95",
                        surprise_factor: Math.min(1.5, Math.max(0.2, toNum(manualMagPct, 5) / 8)).toFixed(2),
                        direct_weights: { [manualSymbol]: 1.0 },
                        auto_approve: true,
                      });
                      setManualHeadline("");
                      setManualBody("");
                      notify("ok", "Created & approved custom news event.");
                    })
                  }
                  className="w-full py-2 rounded bg-emerald-500 hover:bg-emerald-400 text-black font-mono font-bold uppercase disabled:opacity-40"
                >
                  Add Approved Event to Queue
                </button>
              </div>

              {/* Extensible Custom Category Creator */}
              <div className="bg-terminal-panel border border-terminal-border rounded p-4 space-y-2">
                <div className="font-bold uppercase tracking-wider text-white">
                  3. Register Custom Category ({categories.length} Active)
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <input
                    type="text"
                    placeholder="slug_name"
                    value={catSlug}
                    onChange={(e) => setCatSlug(e.target.value)}
                    className="bg-[#070A10] border border-terminal-border rounded px-2 py-1.5 font-mono text-white"
                  />
                  <input
                    type="text"
                    placeholder="Display Name"
                    value={catName}
                    onChange={(e) => setCatName(e.target.value)}
                    className="bg-[#070A10] border border-terminal-border rounded px-2 py-1.5 text-white"
                  />
                </div>
                <button
                  disabled={busy || catSlug.length < 3 || catName.length < 3}
                  onClick={() =>
                    runAction(async () => {
                      await exchangeApi.adminCreateCategory({
                        slug: catSlug.toLowerCase().replace(/[^a-z0-9_]/g, "_"),
                        name: catName,
                        description: "Custom tournament director news category",
                        default_polarity_bias: 1,
                        factor_weights: { india_gdp: 0.5, fiscal_capex: 0.4 },
                      });
                      setCatSlug("");
                      setCatName("");
                      notify("ok", "Custom category added to news engine.");
                    })
                  }
                  className="w-full py-1.5 rounded bg-terminal-elevated border border-terminal-border hover:border-terminal-orange text-slate-200 font-mono font-bold uppercase disabled:opacity-40"
                >
                  + Add Category
                </button>
              </div>
            </div>

            {/* Right 8 Cols: Editorial Queue, Scheduling, Immediate Release & Retraction */}
            <div className="xl:col-span-8 bg-terminal-panel border border-terminal-border rounded flex flex-col overflow-hidden">
              <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-white">
                  Tournament News Queue &amp; Live Release Console ({newsEvents.length})
                </span>
                <div className="flex items-center gap-2 font-mono text-[10px]">
                  <span>SCHED OFFSET (s):</span>
                  <input
                    type="number"
                    min={5}
                    value={scheduleOffsetSec}
                    onChange={(e) => setScheduleOffsetSec(e.target.value)}
                    className="w-16 bg-[#070A10] border border-terminal-border rounded px-1.5 py-0.5 text-white"
                  />
                  {["ALL", "DRAFT", "APPROVED", "SCHEDULED", "RELEASED", "REVERSED"].map((st) => (
                    <button
                      key={st}
                      onClick={() => setNewsStatusFilter(st)}
                      className={`px-2 py-0.5 rounded border ${
                        newsStatusFilter === st
                          ? "bg-terminal-orange text-black font-bold border-terminal-orange"
                          : "border-terminal-border text-terminal-muted"
                      }`}
                    >
                      {st}
                    </button>
                  ))}
                </div>
              </div>

              <div className="overflow-y-auto max-h-[680px] divide-y divide-terminal-border/60">
                {newsEvents
                  .filter((ev) => (newsStatusFilter === "ALL" ? true : ev.status === newsStatusFilter))
                  .map((ev) => (
                    <div key={ev.event_id} className="p-3.5 hover:bg-white/[0.02] space-y-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-1.5 font-mono text-[10px]">
                          <span className="px-2 py-0.5 rounded bg-terminal-elevated border border-terminal-border text-terminal-orange font-bold">
                            {ev.status}
                          </span>
                          <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-200">
                            {ev.severity} • {ev.archetype}
                          </span>
                          <span className="text-terminal-muted">{ev.category_slug}</span>
                          {ev.chain_id && (
                            <span className="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300">
                              CHAIN {ev.chain_stage}/{ev.chain_total_stages}
                            </span>
                          )}
                        </div>

                        <div className="flex items-center gap-1.5 font-mono text-[10px]">
                          {ev.status === "DRAFT" && (
                            <button
                              disabled={busy}
                              onClick={() =>
                                runAction(async () => {
                                  await exchangeApi.adminApproveNews(selectedGameId, ev.event_id);
                                  notify("ok", "News event approved.");
                                })
                              }
                              className="px-2.5 py-1 rounded bg-sky-500/20 border border-sky-500/40 text-sky-300 font-bold"
                            >
                              APPROVE
                            </button>
                          )}

                          {(ev.status === "APPROVED" || ev.status === "SCHEDULED") && (
                            <>
                              <button
                                disabled={busy}
                                onClick={() =>
                                  runAction(async () => {
                                    await exchangeApi.adminReleaseOrScheduleNews(
                                      selectedGameId,
                                      ev.event_id,
                                      {
                                        mode: "SCHEDULED",
                                        scheduled_offset_sec: Math.trunc(
                                          toNum(scheduleOffsetSec, 60)
                                        ),
                                      }
                                    );
                                    notify("ok", `Scheduled at T+${scheduleOffsetSec}s`);
                                  })
                                }
                                className="px-2.5 py-1 rounded bg-amber-500/15 border border-amber-500/40 text-amber-300 font-bold"
                              >
                                SCHEDULE
                              </button>
                              <button
                                disabled={busy}
                                onClick={() =>
                                  runAction(async () => {
                                    await exchangeApi.adminReleaseOrScheduleNews(
                                      selectedGameId,
                                      ev.event_id,
                                      { mode: "IMMEDIATE" }
                                    );
                                    notify("ok", `Released breaking wire: ${ev.headline}`);
                                  })
                                }
                                className="px-2.5 py-1 rounded bg-terminal-orange hover:bg-terminal-orangeHover text-black font-black"
                              >
                                FIRE BREAKING NOW
                              </button>
                            </>
                          )}

                          {ev.status === "RELEASED" && (
                            <button
                              disabled={busy}
                              onClick={() =>
                                runAction(async () => {
                                  await exchangeApi.adminReverseNews(
                                    selectedGameId,
                                    ev.event_id,
                                    "Official Tournament Director Retraction / Reversal"
                                  );
                                  notify("ok", "Issued official retraction & reversed fundamental shock.");
                                })
                              }
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-rose-500/20 border border-rose-500/40 text-rose-300 font-bold"
                            >
                              <RotateCcw className="w-3 h-3" />
                              REVERSE / RETRACT
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="text-xs font-bold text-white">{ev.headline}</div>
                      <p className="text-[11px] text-terminal-muted line-clamp-2">{ev.body}</p>

                      {/* Exact Pre-Computed Stock Impact Preview */}
                      <div className="flex flex-wrap items-center gap-1.5 font-mono text-[10px]">
                        <span className="text-terminal-muted">REF SHOCKS:</span>
                        {ev.impacts.map((imp) => {
                          const signedPct = imp.direction * toNum(imp.magnitude_pct, 0) * 100;
                          return (
                            <span
                              key={imp.symbol}
                              className={`px-1.5 py-0.5 rounded border ${
                                signedPct >= 0
                                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                                  : "bg-rose-500/10 border-rose-500/30 text-rose-300"
                              }`}
                            >
                              {imp.symbol} {signedPct >= 0 ? `+${signedPct.toFixed(2)}%` : `${signedPct.toFixed(2)}%`}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: GAME SETUP, CONFIG & EMERGENCY LIFECYCLE CONTROLS */}
        {tab === "LIFECYCLE" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 text-xs">
            {/* Lifecycle & Emergency Controls on Selected Game */}
            <div className="bg-terminal-panel border border-terminal-border rounded p-5 space-y-4">
              <div className="font-bold uppercase tracking-wider text-terminal-orange flex items-center gap-2">
                <Shield className="w-4 h-4" />
                Live Phase &amp; Emergency Circuit Controls ({activeGame?.code})
              </div>

              <div>
                <label className="block text-[10px] font-mono uppercase text-terminal-muted mb-1">
                  Mandatory Audit Reason (Recorded in Immutable Ledger)
                </label>
                <input
                  type="text"
                  value={actionReason}
                  onChange={(e) => setActionReason(e.target.value)}
                  className="w-full bg-[#070A10] border border-terminal-borderBright rounded px-3 py-2 text-white font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-2.5 font-mono">
                <button
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      await exchangeApi.adminLifecycleAction(selectedGameId, "start", actionReason);
                      notify("ok", "Started Phase A (45m Main Trading)!");
                    })
                  }
                  className="py-2.5 px-3 rounded bg-emerald-500 hover:bg-emerald-400 text-black font-black flex items-center justify-center gap-1.5 col-span-2"
                >
                  <Play className="w-3.5 h-3.5" />
                  1. START PHASE A (45m MAIN TRADING)
                </button>

                <button
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      await exchangeApi.adminLifecycleAction(selectedGameId, "pause", actionReason);
                      notify("ok", "Trading paused via circuit breaker.");
                    })
                  }
                  className="py-2.5 px-3 rounded bg-amber-500/20 border border-amber-500/40 text-amber-300 font-bold flex items-center justify-center gap-1.5"
                >
                  <Pause className="w-3.5 h-3.5" />
                  PAUSE (CIRCUIT BREAKER)
                </button>

                <button
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      await exchangeApi.adminLifecycleAction(selectedGameId, "resume", actionReason);
                      notify("ok", "Resumed trading clock.");
                    })
                  }
                  className="py-2.5 px-3 rounded bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-bold"
                >
                  RESUME TRADING
                </button>

                <button
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      await exchangeApi.adminLifecycleAction(
                        selectedGameId,
                        "start-settlement",
                        actionReason
                      );
                      notify("ok", "Transitioned to Phase B (5m Close-Only Short Settlement)!");
                    })
                  }
                  className="py-2.5 px-3 rounded bg-terminal-orange text-black font-black"
                >
                  2. ENTER PHASE B (5m SETTLE)
                </button>

                <button
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      await exchangeApi.adminLifecycleAction(selectedGameId, "finalize", actionReason);
                      notify("ok", "Finalized short liquidations & locked official rankings!");
                    })
                  }
                  className="py-2.5 px-3 rounded bg-sky-400 text-black font-black"
                >
                  3. FINALIZE &amp; LOCK RANKINGS
                </button>
              </div>

              <div className="pt-3 border-t border-terminal-border">
                <button
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      const res = await exchangeApi.adminCancelAllOrders(selectedGameId, actionReason);
                      notify("ok", `Emergency cancelled ${res.cancelled_orders} open orders & released reservations.`);
                    })
                  }
                  className="w-full py-2.5 rounded bg-rose-500/20 border border-rose-500/50 hover:bg-rose-500/30 text-rose-200 font-mono font-bold flex items-center justify-center gap-2"
                >
                  <Trash2 className="w-4 h-4" />
                  EMERGENCY CANCEL ALL RESTING OPEN ORDERS
                </button>
              </div>
            </div>

            {/* Create New Tournament Instance */}
            <div className="bg-terminal-panel border border-terminal-border rounded p-5 space-y-3">
              <div className="font-bold uppercase tracking-wider text-white flex items-center gap-1.5">
                <Plus className="w-4 h-4 text-terminal-orange" />
                Provision New Tournament Round / Heat
              </div>

              <div className="grid grid-cols-2 gap-3 font-mono">
                <div>
                  <label className="block text-[10px] text-terminal-muted mb-1">GAME CODE</label>
                  <input
                    type="text"
                    value={newGameCode}
                    onChange={(e) => setNewGameCode(e.target.value.toUpperCase())}
                    className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-terminal-muted mb-1">GAME NAME</label>
                  <input
                    type="text"
                    value={newGameName}
                    onChange={(e) => setNewGameName(e.target.value)}
                    className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white font-sans"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-terminal-muted mb-1">
                    PHASE A TRADING (SEC)
                  </label>
                  <input
                    type="number"
                    value={newTradingSec}
                    onChange={(e) => setNewTradingSec(e.target.value)}
                    className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-terminal-muted mb-1">
                    PHASE B SETTLEMENT (SEC)
                  </label>
                  <input
                    type="number"
                    value={newSettleSec}
                    onChange={(e) => setNewSettleSec(e.target.value)}
                    className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-terminal-muted mb-1">
                    BORROW POOL / STOCK
                  </label>
                  <input
                    type="number"
                    value={newPoolShares}
                    onChange={(e) => setNewPoolShares(e.target.value)}
                    className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-terminal-muted mb-1">
                    MAX PLAYER SHORT / STOCK
                  </label>
                  <input
                    type="number"
                    value={newShortLimit}
                    onChange={(e) => setNewShortLimit(e.target.value)}
                    className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-terminal-muted mb-1">
                    INITIAL MARGIN RATIO
                  </label>
                  <input
                    type="number"
                    step={0.05}
                    value={newInitMargin}
                    onChange={(e) => setNewInitMargin(e.target.value)}
                    className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-terminal-muted mb-1">
                    MAINTENANCE MARGIN RATIO
                  </label>
                  <input
                    type="number"
                    step={0.05}
                    value={newMaintMargin}
                    onChange={(e) => setNewMaintMargin(e.target.value)}
                    className="w-full bg-[#070A10] border border-terminal-border rounded px-2.5 py-1.5 text-white"
                  />
                </div>
              </div>

              <button
                disabled={busy}
                onClick={() =>
                  runAction(async () => {
                    const created = await exchangeApi.adminCreateGame({
                      code: newGameCode,
                      name: newGameName,
                      trading_duration_sec: Math.trunc(toNum(newTradingSec, 2700)),
                      settlement_duration_sec: Math.trunc(toNum(newSettleSec, 300)),
                      default_short_pool_shares: Math.trunc(toNum(newPoolShares, 15000)),
                      short_position_limit_per_stock: Math.trunc(toNum(newShortLimit, 500)),
                      initial_margin_ratio: newInitMargin,
                      maintenance_margin_ratio: newMaintMargin,
                    });
                    setSelectedGameId(created.game_id);
                    notify("ok", `Provisioned game ${created.code} with 5 simulated Indian stocks.`);
                  })
                }
                className="w-full py-2.5 rounded bg-terminal-orange hover:bg-terminal-orangeHover text-black font-mono font-black uppercase"
              >
                Create New Tournament Instance
              </button>
            </div>
          </div>
        )}

        {/* TAB 4: IMMUTABLE SHA-256 HASH-CHAINED AUDIT TRAIL */}
        {tab === "AUDIT" && (
          <div className="bg-terminal-panel border border-terminal-border rounded overflow-hidden">
            <div className="px-4 py-2.5 border-b border-terminal-border bg-[#090D15] flex justify-between items-center">
              <span className="text-xs font-bold uppercase tracking-wider text-white">
                PostgreSQL Trigger-Protected Immutable Audit Trail ({auditLogs.length} Recent Entries)
              </span>
              <span className="text-[10px] font-mono text-emerald-400">
                BEFORE UPDATE OR DELETE RAISE EXCEPTION TRIGGER ACTIVE
              </span>
            </div>
            <div className="overflow-x-auto max-h-[620px]">
              <table className="w-full text-left font-mono text-xs">
                <thead className="bg-[#070A10] text-[10px] uppercase text-terminal-muted">
                  <tr>
                    <th className="px-3 py-2">Seq</th>
                    <th className="px-3 py-2">Timestamp</th>
                    <th className="px-3 py-2">Role</th>
                    <th className="px-3 py-2">Event Type</th>
                    <th className="px-3 py-2 font-sans">Reason / Details</th>
                    <th className="px-3 py-2">SHA-256 Chain Hash</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-terminal-border/50">
                  {auditLogs.map((a) => (
                    <tr key={a.audit_id} className="hover:bg-white/[0.02]">
                      <td className="px-3 py-1.5 text-terminal-muted">#{a.seq_id}</td>
                      <td className="px-3 py-1.5 text-slate-300">
                        {new Date(a.created_at).toLocaleTimeString("en-IN", { hour12: false })}
                      </td>
                      <td className="px-3 py-1.5 text-terminal-orange">{a.actor_role}</td>
                      <td className="px-3 py-1.5 font-bold text-white">{a.event_type}</td>
                      <td className="px-3 py-1.5 font-sans text-slate-300 text-[11px]">
                        <div>{a.reason || "—"}</div>
                        <div className="font-mono text-[10px] text-terminal-muted truncate max-w-md">
                          {JSON.stringify(a.payload)}
                        </div>
                      </td>
                      <td className="px-3 py-1.5 text-[10px] text-emerald-400">
                        {a.entry_hash.slice(0, 18)}…
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
