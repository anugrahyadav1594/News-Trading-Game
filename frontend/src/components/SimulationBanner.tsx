"use client";

import React from "react";
import { AlertTriangle, CheckCircle2, Info, ShieldAlert, X } from "lucide-react";
import { useTerminalStore } from "@/store/terminalStore";

export function SimulationBanner() {
  const wsStatus = useTerminalStore((s) => s.wsStatus);
  const toasts = useTerminalStore((s) => s.toasts);
  const dismissToast = useTerminalStore((s) => s.dismissToast);

  return (
    <>
      <div className="w-full bg-[#0D131F] border-b border-terminal-border px-3 py-1 flex items-center justify-between text-[11px] tracking-wide select-none">
        <div className="flex items-center gap-2 text-terminal-muted">
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-terminal-orange/15 text-terminal-orange font-semibold uppercase tracking-wider text-[10px] border border-terminal-orange/30">
            <ShieldAlert className="w-3 h-3" />
            Tournament Simulation
          </span>
          <span className="truncate">
            MUMBAI TRADING TOURNAMENT (ROUND 1) • ORGANIZED BY{" "}
            <strong className="text-terminal-text font-medium">QUANTRELIC ANALYTICS</strong> • ALL
            PRICES REBASED AT ₹1,000.00 &amp; NEWS SCENARIOS ARE FICTIONAL SIMULATION ARTIFACTS (NOT
            LIVE NSE/BSE DATA)
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0 font-mono">
          <span
            className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-semibold ${
              wsStatus === "LIVE"
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : wsStatus === "CONNECTING"
                ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
                : "bg-slate-500/10 border-slate-500/30 text-slate-400"
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                wsStatus === "LIVE"
                  ? "bg-emerald-400 animate-pulse"
                  : wsStatus === "CONNECTING"
                  ? "bg-amber-400 animate-pulse"
                  : "bg-slate-400"
              }`}
            />
            {wsStatus === "LIVE" ? "WS STREAM LIVE" : wsStatus === "CONNECTING" ? "WS SYNCING" : "REST SYNC"}
          </span>
        </div>
      </div>

      {/* Floating Institutional Toast Stack */}
      {toasts.length > 0 && (
        <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-md w-full pointer-events-none">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`pointer-events-auto rounded border px-3.5 py-2.5 shadow-2xl backdrop-blur-md flex items-start gap-2.5 text-xs ${
                t.tone === "success"
                  ? "bg-[#091914]/95 border-emerald-500/40 text-emerald-100"
                  : t.tone === "error"
                  ? "bg-[#1F0B10]/95 border-rose-500/50 text-rose-100"
                  : t.tone === "warning"
                  ? "bg-[#1F1507]/95 border-terminal-orange/50 text-amber-100"
                  : "bg-[#0C1424]/95 border-sky-500/40 text-sky-100"
              }`}
            >
              {t.tone === "success" ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
              ) : t.tone === "error" || t.tone === "warning" ? (
                <AlertTriangle className="w-4 h-4 text-terminal-orange shrink-0 mt-0.5" />
              ) : (
                <Info className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
              )}
              <div className="flex-1 min-w-0">
                <div className="font-semibold tracking-wide uppercase text-[11px]">{t.title}</div>
                {t.detail && <div className="text-slate-300 mt-0.5 leading-snug">{t.detail}</div>}
              </div>
              <button
                onClick={() => dismissToast(t.id)}
                className="text-slate-400 hover:text-white p-0.5"
                aria-label="Dismiss notification"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
