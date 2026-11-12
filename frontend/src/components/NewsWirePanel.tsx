"use client";

import React, { useState } from "react";
import { GitBranch, Newspaper, Radio, RotateCcw, X } from "lucide-react";
import { useTerminalStore } from "@/store/terminalStore";
import type { ReleasedNewsItem } from "@/types/exchange";

interface Props {
  filterSymbol?: string;
  maxHeightClass?: string;
}

export function NewsWirePanel({ filterSymbol, maxHeightClass = "max-h-[380px]" }: Props) {
  const newsFeed = useTerminalStore((s) => s.newsFeed);
  const setSelectedSymbol = useTerminalStore((s) => s.setSelectedSymbol);
  const [selectedStory, setSelectedStory] = useState<ReleasedNewsItem | null>(null);
  const [localFilter, setLocalFilter] = useState<string>("ALL");

  const activeSymFilter = filterSymbol || (localFilter !== "ALL" ? localFilter : null);

  const visibleItems = newsFeed.filter((item) => {
    if (!activeSymFilter) return true;
    return item.affected_symbols.includes(activeSymFilter);
  });

  return (
    <div className="bg-terminal-panel border border-terminal-border rounded flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-terminal-border flex items-center justify-between bg-[#090D15]">
        <div className="flex items-center gap-1.5">
          <Radio className="w-3.5 h-3.5 text-terminal-orange animate-pulse" />
          <span className="text-xs font-bold uppercase tracking-wider text-white">
            Simulated Breaking Wire
          </span>
        </div>
        {!filterSymbol && (
          <select
            aria-label="Filter news by stock"
            value={localFilter}
            onChange={(e) => setLocalFilter(e.target.value)}
            className="bg-terminal-elevated border border-terminal-border text-[10px] font-mono text-slate-200 rounded px-1.5 py-0.5"
          >
            <option value="ALL">ALL STOCKS</option>
            <option value="RELIANCE">RELIANCE</option>
            <option value="ICICIBANK">ICICIBANK</option>
            <option value="TATAMOTORS">TATAMOTORS</option>
            <option value="SUNPHARMA">SUNPHARMA</option>
            <option value="INFY">INFY</option>
          </select>
        )}
      </div>

      <div className={`overflow-y-auto divide-y divide-terminal-border/60 ${maxHeightClass}`}>
        {visibleItems.length === 0 ? (
          <div className="p-6 text-center text-xs text-terminal-muted">
            <Newspaper className="w-5 h-5 mx-auto mb-1.5 opacity-50" />
            No simulated headlines released yet for this filter.
          </div>
        ) : (
          visibleItems.map((item) => {
            const isReversed = item.status === "REVERSED";
            return (
              <div
                key={item.event_id}
                onClick={() => setSelectedStory(item)}
                className={`p-2.5 hover:bg-white/[0.03] transition cursor-pointer ${
                  isReversed ? "opacity-60" : ""
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-1 mb-1">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold uppercase ${
                        isReversed
                          ? "bg-slate-600/30 text-slate-300 line-through"
                          : item.severity === "CRITICAL" || item.severity === "HIGH"
                          ? "bg-terminal-orange/20 text-terminal-orange border border-terminal-orange/40"
                          : item.archetype === "RUMOUR"
                          ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                          : "bg-sky-500/15 text-sky-300 border border-sky-500/30"
                      }`}
                    >
                      {isReversed ? "RETRACTED" : `${item.severity} • ${item.archetype}`}
                    </span>

                    {item.chain_id && (
                      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-purple-500/15 border border-purple-500/30 text-purple-300 text-[9px] font-mono">
                        <GitBranch className="w-2.5 h-2.5" />
                        STAGE {item.chain_stage}/{item.chain_total_stages}
                      </span>
                    )}
                  </div>

                  <span className="text-[10px] font-mono text-terminal-muted">
                    {item.released_at
                      ? new Date(item.released_at).toLocaleTimeString("en-IN", { hour12: false })
                      : ""}
                  </span>
                </div>

                <div
                  className={`text-xs font-semibold leading-snug ${
                    isReversed ? "line-through text-slate-400" : "text-slate-100"
                  }`}
                >
                  {item.headline}
                </div>

                <div className="mt-1.5 flex flex-wrap items-center gap-1">
                  {item.affected_symbols.map((sym) => (
                    <button
                      key={sym}
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedSymbol(sym);
                      }}
                      className="px-1.5 py-0.5 rounded bg-terminal-elevated border border-terminal-border hover:border-terminal-orange text-[10px] font-mono text-terminal-orange"
                    >
                      {sym}
                    </button>
                  ))}
                  <span className="text-[9px] text-terminal-muted ml-auto uppercase font-mono">
                    SIMULATED
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Story Inspection Modal */}
      {selectedStory && (
        <div
          className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setSelectedStory(null)}
        >
          <div
            className="bg-terminal-panel border border-terminal-borderBright rounded-lg max-w-xl w-full p-5 shadow-2xl space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-terminal-orange/20 border border-terminal-orange/40 text-terminal-orange font-mono text-[10px] font-bold uppercase">
                  {selectedStory.severity} • {selectedStory.archetype}
                </span>
                {selectedStory.status === "REVERSED" && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-rose-500/20 border border-rose-500/40 text-rose-300 font-mono text-[10px] font-bold">
                    <RotateCcw className="w-3 h-3" /> RETRACTED / REVERSED
                  </span>
                )}
                {selectedStory.chain_id && (
                  <span className="px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 font-mono text-[10px]">
                    NARRATIVE CHAIN STAGE {selectedStory.chain_stage}/{selectedStory.chain_total_stages}
                  </span>
                )}
              </div>
              <button
                onClick={() => setSelectedStory(null)}
                className="text-terminal-muted hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <h3 className="text-base font-bold text-white leading-snug">
              {selectedStory.headline}
            </h3>

            <p className="text-xs text-slate-300 leading-relaxed bg-[#070A10] border border-terminal-border p-3 rounded">
              {selectedStory.body}
            </p>

            <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono">
              <div className="flex items-center gap-1.5">
                <span className="text-terminal-muted">AFFECTED SYMBOLS:</span>
                {selectedStory.affected_symbols.map((sym) => (
                  <button
                    key={sym}
                    onClick={() => {
                      setSelectedSymbol(sym);
                      setSelectedStory(null);
                    }}
                    className="px-2 py-0.5 rounded bg-terminal-elevated border border-terminal-orange/40 text-terminal-orange font-bold"
                  >
                    {sym}
                  </button>
                ))}
              </div>
              <span className="text-terminal-muted">
                CERTAINTY WEIGHT: {(Number(selectedStory.certainty_pct) * 100).toFixed(0)}%
              </span>
            </div>

            <div className="text-[10px] text-amber-300/90 bg-amber-500/10 border border-amber-500/30 rounded px-2.5 py-1.5">
              {selectedStory.simulation_disclaimer}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
