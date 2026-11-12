"use client";

import React, { useEffect, useRef } from "react";
import { ColorType, CrosshairMode, type IChartApi, type ISeriesApi, type UTCTimestamp, createChart } from "lightweight-charts";
import { formatPrice, formatQty, formatSignedPct, toNum } from "@/lib/format";
import { useTerminalStore } from "@/store/terminalStore";

interface Props {
  height?: number;
}

export function CandlestickChart({ height = 320 }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const refLineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const selectedSymbol = useTerminalStore((s) => s.selectedSymbol);
  const stocks = useTerminalStore((s) => s.stocks);
  const candles = useTerminalStore((s) => s.candles);
  const candleInterval = useTerminalStore((s) => s.candleInterval);
  const setCandleInterval = useTerminalStore((s) => s.setCandleInterval);

  const stock = stocks.find((s) => s.symbol === selectedSymbol);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#0B0F17" },
        textColor: "#8A99B0",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#151D2B" },
        horzLines: { color: "#151D2B" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: "#1C2536",
      },
      timeScale: {
        borderColor: "#1C2536",
        timeVisible: true,
        secondsVisible: true,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#10B981",
      downColor: "#F43F5E",
      borderUpColor: "#10B981",
      borderDownColor: "#F43F5E",
      wickUpColor: "#10B981",
      wickDownColor: "#F43F5E",
    });

    const refLineSeries = chart.addLineSeries({
      color: "#FF6B00",
      lineWidth: 2,
      lineStyle: 2,
      title: "Ref Price",
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    refLineSeriesRef.current = refLineSeries;

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      refLineSeriesRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    if (!candleSeriesRef.current || !refLineSeriesRef.current) return;

    const refPx = toNum(stock?.fundamental_ref_price, 1000);
    const mtmPx = toNum(stock?.official_mtm_price, 1000);
    const nowTs = Math.floor(Date.now() / 1000);

    const sorted = [...candles]
      .sort((a, b) => a.time - b.time)
      .filter((bar, idx, arr) => idx === 0 || bar.time > arr[idx - 1].time);

    if (sorted.length > 0) {
      candleSeriesRef.current.setData(
        sorted.map((b) => ({
          time: b.time as UTCTimestamp,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }))
      );
      refLineSeriesRef.current.setData(
        sorted.map((b, i) => ({
          time: b.time as UTCTimestamp,
          value: i === sorted.length - 1 ? refPx : b.close,
        }))
      );
    } else {
      // Seed clean flat baseline bars at opening ₹1,000 -> current MTM if no trade bar exists yet
      const t1 = (nowTs - 60) as UTCTimestamp;
      const t2 = nowTs as UTCTimestamp;
      candleSeriesRef.current.setData([
        { time: t1, open: 1000, high: 1000, low: 1000, close: 1000 },
        {
          time: t2,
          open: 1000,
          high: Math.max(1000, mtmPx),
          low: Math.min(1000, mtmPx),
          close: mtmPx,
        },
      ]);
      refLineSeriesRef.current.setData([
        { time: t1, value: 1000 },
        { time: t2, value: refPx },
      ]);
    }
  }, [candles, stock?.fundamental_ref_price, stock?.official_mtm_price, selectedSymbol]);

  const chgPct = toNum(stock?.change_pct_from_open, 0);
  const poolRem = stock?.borrow_pool?.remaining_shares ?? 0;
  const poolTot = stock?.borrow_pool?.total_pool_shares ?? 1;

  return (
    <div className="bg-terminal-panel border border-terminal-border rounded flex flex-col overflow-hidden">
      {/* Stock Instrument Telemetry Strip */}
      <div className="px-3 py-2 border-b border-terminal-border flex flex-wrap items-center justify-between gap-3 bg-[#090D15]">
        <div className="flex items-center gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono font-black text-base text-white">{selectedSymbol}</span>
              <span className="text-[11px] px-1.5 py-0.5 rounded bg-terminal-elevated border border-terminal-border text-terminal-muted">
                {stock?.sector || "EQUITY"}
              </span>
            </div>
            <div className="text-[11px] text-terminal-muted">{stock?.company_name}</div>
          </div>

          <div className="h-7 w-px bg-terminal-border" />

          <div className="font-mono">
            <div className="text-[10px] text-terminal-muted uppercase">Last Traded (P2P)</div>
            <div className="text-sm font-bold text-white flex items-center gap-1.5 tabular-nums">
              {stock?.last_traded_price ? formatPrice(stock.last_traded_price) : "NO PRINT"}
              <span
                className={`text-xs font-semibold ${
                  chgPct > 0.01
                    ? "text-terminal-bid"
                    : chgPct < -0.01
                    ? "text-terminal-ask"
                    : "text-slate-400"
                }`}
              >
                ({formatSignedPct(chgPct)})
              </span>
            </div>
          </div>

          <div className="font-mono hidden sm:block">
            <div className="text-[10px] text-terminal-orange uppercase">Fundamental Ref</div>
            <div className="text-xs font-bold text-terminal-orange tabular-nums">
              {formatPrice(stock?.fundamental_ref_price)}
            </div>
          </div>

          <div className="font-mono hidden md:block">
            <div className="text-[10px] text-terminal-muted uppercase">Official MTM</div>
            <div className="text-xs font-semibold text-sky-300 tabular-nums">
              {formatPrice(stock?.official_mtm_price)}
            </div>
          </div>

          <div className="font-mono hidden xl:block">
            <div className="text-[10px] text-terminal-muted uppercase">Short Borrow Pool</div>
            <div className="text-xs text-slate-200 tabular-nums">
              {formatQty(poolRem)} <span className="text-terminal-muted">/ {formatQty(poolTot)} sh</span>
            </div>
          </div>
        </div>

        {/* Timeframe Selector */}
        <div className="flex items-center gap-1 font-mono text-xs">
          <span className="text-[10px] text-terminal-muted mr-1 uppercase">Bar:</span>
          {([5, 60] as const).map((sec) => (
            <button
              key={sec}
              onClick={() => setCandleInterval(sec)}
              className={`px-2 py-1 rounded border transition ${
                candleInterval === sec
                  ? "bg-terminal-orange text-black font-bold border-terminal-orange"
                  : "bg-terminal-elevated text-terminal-muted border-terminal-border hover:text-white"
              }`}
            >
              {sec === 5 ? "5s" : "1m"}
            </button>
          ))}
        </div>
      </div>

      {/* Canvas Chart */}
      <div ref={containerRef} className="w-full" style={{ height }} />
    </div>
  );
}
