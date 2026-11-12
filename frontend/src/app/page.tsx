"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Lock, Shield, ShieldAlert, Terminal, UserPlus, Users } from "lucide-react";
import { useAuthStore } from "@/store/authStore";

const QUICK_ACCOUNTS = [
  {
    label: "Tournament Director (Admin)",
    sub: "Control Room, News Desk & Surveillance",
    email: "admin@quantrelic-mtt.in",
    pass: "MttAdmin@2026!",
    role: "ADMIN" as const,
  },
  {
    label: "Aarav Mehta • IIT Bombay",
    sub: "Player Seat #1 (MTT-ROUND1)",
    email: "aarav@mtt.in",
    pass: "MttPlayer@2026!",
    role: "PLAYER" as const,
  },
  {
    label: "Diya Kulkarni • IIM Ahmedabad",
    sub: "Player Seat #2 (MTT-ROUND1)",
    email: "diya@mtt.in",
    pass: "MttPlayer@2026!",
    role: "PLAYER" as const,
  },
  {
    label: "Rohan Deshmukh • VJTI Mumbai",
    sub: "Player Seat #3 (MTT-ROUND1)",
    email: "rohan@mtt.in",
    pass: "MttPlayer@2026!",
    role: "PLAYER" as const,
  },
  {
    label: "Ananya Iyer • ISI Kolkata",
    sub: "Player Seat #4 (MTT-ROUND1)",
    email: "ananya@mtt.in",
    pass: "MttPlayer@2026!",
    role: "PLAYER" as const,
  },
];

export default function EntryGatePage() {
  const router = useRouter();
  const { user, hydrated, hydrate, login, register, loading, error } = useAuthStore();

  const [mode, setMode] = useState<"LOGIN" | "REGISTER">("LOGIN");
  const [email, setEmail] = useState("aarav@mtt.in");
  const [password, setPassword] = useState("MttPlayer@2026!");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [institution, setInstitution] = useState("");

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (mode === "LOGIN") {
        const u = await login(email, password);
        router.push(u.role === "ADMIN" ? "/admin" : "/terminal");
      } else {
        const u = await register({
          email,
          username,
          password,
          display_name: displayName || username,
          institution: institution || undefined,
        });
        router.push(u.role === "ADMIN" ? "/admin" : "/terminal");
      }
    } catch {
      // handled in store error
    }
  };

  const handleQuickLogin = async (accEmail: string, accPass: string, role: "ADMIN" | "PLAYER") => {
    try {
      await login(accEmail, accPass);
      router.push(role === "ADMIN" ? "/admin" : "/terminal");
    } catch {
      // handled in store
    }
  };

  return (
    <div className="min-h-screen bg-terminal-bg flex flex-col">
      {/* Top Mandatory Simulation Disclaimer */}
      <div className="bg-[#0D131F] border-b border-terminal-border px-4 py-2 text-center text-xs text-terminal-muted flex items-center justify-center gap-2">
        <ShieldAlert className="w-4 h-4 text-terminal-orange shrink-0" />
        <span>
          <strong className="text-terminal-orange">TOURNAMENT SIMULATION PLATFORM:</strong> All stock
          prices (rebased at ₹1,000.00) and breaking news scenarios in NEWS TRADING — MTT are
          fictional tournament constructs created for Quantrelic Analytics. Never real NSE/BSE data.
        </span>
      </div>

      <main className="flex-1 max-w-6xl w-full mx-auto px-4 py-10 grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
        {/* Left 7 Cols: Tournament Briefing & Quick Demo Access */}
        <div className="lg:col-span-7 space-y-6">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded bg-terminal-orange/15 border border-terminal-orange/40 text-terminal-orange font-mono text-xs font-bold">
              MUMBAI TRADING TOURNAMENT • ROUND 1 CHAMPIONSHIP
            </div>
            <h1 className="text-4xl font-black tracking-tight text-white">
              NEWS TRADING <span className="text-terminal-orange">— MTT</span>
            </h1>
            <p className="text-sm text-slate-300 leading-relaxed max-w-2xl">
              Institutional peer-to-peer continuous double auction exchange engineered for{" "}
              <strong className="text-white">Quantrelic Analytics</strong>. Trade 5 simulated Indian
              large-cap equities across a 45-minute Main Trading session followed by a 5-minute
              mandatory Short Position Settlement window.
            </p>
          </div>

          {/* Active Session Banner if already logged in */}
          {hydrated && user && (
            <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/40 flex items-center justify-between gap-4">
              <div>
                <div className="text-xs font-mono text-emerald-300 uppercase">
                  Authenticated Session Active
                </div>
                <div className="text-sm font-bold text-white">
                  {user.display_name} ({user.role})
                </div>
              </div>
              <div className="flex items-center gap-2">
                {user.role === "ADMIN" && (
                  <button
                    onClick={() => router.push("/admin")}
                    className="px-4 py-2 rounded bg-terminal-orange text-black font-mono font-bold text-xs uppercase flex items-center gap-1.5"
                  >
                    <Shield className="w-3.5 h-3.5" />
                    Control Room
                  </button>
                )}
                <button
                  onClick={() => router.push("/terminal")}
                  className="px-4 py-2 rounded bg-emerald-500 text-black font-mono font-bold text-xs uppercase flex items-center gap-1.5"
                >
                  <Terminal className="w-3.5 h-3.5" />
                  Trading Floor
                </button>
              </div>
            </div>
          )}

          {/* Key Engine Specs */}
          <div className="grid grid-cols-3 gap-3 font-mono">
            <div className="bg-terminal-panel border border-terminal-border rounded p-3">
              <div className="text-[10px] text-terminal-muted uppercase">Starting Net Worth</div>
              <div className="text-base font-black text-terminal-orange mt-0.5">₹10,00,000</div>
              <div className="text-[10px] text-slate-400">₹5L Cash + 5×100 Shares</div>
            </div>
            <div className="bg-terminal-panel border border-terminal-border rounded p-3">
              <div className="text-[10px] text-terminal-muted uppercase">Price Discovery</div>
              <div className="text-base font-black text-white mt-0.5">100% P2P CDA</div>
              <div className="text-[10px] text-slate-400">Price-Time Priority</div>
            </div>
            <div className="bg-terminal-panel border border-terminal-border rounded p-3">
              <div className="text-[10px] text-terminal-muted uppercase">Lifecycle Clock</div>
              <div className="text-base font-black text-emerald-400 mt-0.5">45m + 5m</div>
              <div className="text-[10px] text-slate-400">Auto Short Settlement</div>
            </div>
          </div>

          {/* 1-Click Tournament Seat Switcher */}
          <div className="bg-terminal-panel border border-terminal-border rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-terminal-orange" />
                Instant Seeded Tournament Seats (Real JWT Auth)
              </span>
              <span className="text-[10px] font-mono text-terminal-muted">CLICK TO ENTER</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {QUICK_ACCOUNTS.map((acc) => (
                <button
                  key={acc.email}
                  type="button"
                  disabled={loading}
                  onClick={() => handleQuickLogin(acc.email, acc.pass, acc.role)}
                  className={`p-2.5 rounded border text-left transition flex items-center justify-between group ${
                    acc.role === "ADMIN"
                      ? "bg-terminal-orange/10 border-terminal-orange/50 hover:bg-terminal-orange/20 sm:col-span-2"
                      : "bg-terminal-elevated border-terminal-border hover:border-terminal-orange"
                  }`}
                >
                  <div>
                    <div className="text-xs font-bold text-white flex items-center gap-1.5">
                      {acc.role === "ADMIN" && <Shield className="w-3.5 h-3.5 text-terminal-orange" />}
                      {acc.label}
                    </div>
                    <div className="text-[11px] text-terminal-muted">{acc.sub}</div>
                  </div>
                  <ArrowRight className="w-4 h-4 text-terminal-muted group-hover:text-terminal-orange transition" />
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right 5 Cols: Credential Sign-In / Competitor Registration Card */}
        <div className="lg:col-span-5">
          <div className="bg-terminal-panel border border-terminal-borderBright rounded-xl p-6 shadow-2xl space-y-5">
            <div className="grid grid-cols-2 gap-1 bg-[#070A10] p-1 rounded border border-terminal-border font-mono text-xs">
              <button
                type="button"
                onClick={() => setMode("LOGIN")}
                className={`py-2 rounded font-bold flex items-center justify-center gap-1.5 ${
                  mode === "LOGIN"
                    ? "bg-terminal-orange text-black"
                    : "text-terminal-muted hover:text-white"
                }`}
              >
                <Lock className="w-3.5 h-3.5" />
                SIGN IN
              </button>
              <button
                type="button"
                onClick={() => {
                  setMode("REGISTER");
                  setEmail("");
                  setPassword("");
                }}
                className={`py-2 rounded font-bold flex items-center justify-center gap-1.5 ${
                  mode === "REGISTER"
                    ? "bg-terminal-orange text-black"
                    : "text-terminal-muted hover:text-white"
                }`}
              >
                <UserPlus className="w-3.5 h-3.5" />
                REGISTER PLAYER
              </button>
            </div>

            <form onSubmit={handleAuthSubmit} className="space-y-3.5 text-xs">
              <div>
                <label className="block text-[11px] font-mono uppercase text-terminal-muted mb-1">
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="competitor@college.edu.in"
                  className="w-full bg-[#070A10] border border-terminal-borderBright rounded px-3 py-2 text-white font-mono focus:outline-none focus:border-terminal-orange"
                />
              </div>

              {mode === "REGISTER" && (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-[11px] font-mono uppercase text-terminal-muted mb-1">
                        Username
                      </label>
                      <input
                        type="text"
                        required
                        minLength={3}
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        placeholder="quant_trader"
                        className="w-full bg-[#070A10] border border-terminal-borderBright rounded px-3 py-2 text-white font-mono focus:outline-none focus:border-terminal-orange"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-mono uppercase text-terminal-muted mb-1">
                        Full Name
                      </label>
                      <input
                        type="text"
                        required
                        value={displayName}
                        onChange={(e) => setDisplayName(e.target.value)}
                        placeholder="Vikram Rao"
                        className="w-full bg-[#070A10] border border-terminal-borderBright rounded px-3 py-2 text-white focus:outline-none focus:border-terminal-orange"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-mono uppercase text-terminal-muted mb-1">
                      Institution / Team (Optional)
                    </label>
                    <input
                      type="text"
                      value={institution}
                      onChange={(e) => setInstitution(e.target.value)}
                      placeholder="IIT Bombay / Quant Club"
                      className="w-full bg-[#070A10] border border-terminal-borderBright rounded px-3 py-2 text-white focus:outline-none focus:border-terminal-orange"
                    />
                  </div>
                </>
              )}

              <div>
                <label className="block text-[11px] font-mono uppercase text-terminal-muted mb-1">
                  Password
                </label>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-[#070A10] border border-terminal-borderBright rounded px-3 py-2 text-white font-mono focus:outline-none focus:border-terminal-orange"
                />
              </div>

              {error && (
                <div className="p-2.5 rounded bg-rose-500/15 border border-rose-500/40 text-rose-200 text-xs">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 rounded bg-terminal-orange hover:bg-terminal-orangeHover text-black font-mono font-black uppercase tracking-wider transition shadow-lg disabled:opacity-50"
              >
                {loading
                  ? "AUTHENTICATING..."
                  : mode === "LOGIN"
                  ? "ENTER EXCHANGE TERMINAL"
                  : "CREATE SEAT & ENTER EXCHANGE"}
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
}
