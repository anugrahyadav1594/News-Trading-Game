"use client";

import React, { useEffect } from "react";
import { useRouter } from "next/navigation";
import { BottomBlotter } from "@/components/BottomBlotter";
import { CandlestickChart } from "@/components/CandlestickChart";
import { NewsWirePanel } from "@/components/NewsWirePanel";
import { OrderBookLadder } from "@/components/OrderBookLadder";
import { OrderTicket } from "@/components/OrderTicket";
import { SimulationBanner } from "@/components/SimulationBanner";
import { TopCommandBar } from "@/components/TopCommandBar";
import { WatchlistPanel } from "@/components/WatchlistPanel";
import { HistoryView } from "@/components/views/HistoryView";
import { LeaderboardView } from "@/components/views/LeaderboardView";
import { LobbyView } from "@/components/views/LobbyView";
import { PortfolioView } from "@/components/views/PortfolioView";
import { StockDetailView } from "@/components/views/StockDetailView";
import { useAuthStore } from "@/store/authStore";
import { useTerminalStore } from "@/store/terminalStore";

export default function TradingTerminalPage() {
  const router = useRouter();
  const { user, hydrated, hydrate } = useAuthStore();
  const activeTab = useTerminalStore((s) => s.activeTab);
  const loadGamesAndSelectDefault = useTerminalStore((s) => s.loadGamesAndSelectDefault);
  const disconnectStream = useTerminalStore((s) => s.disconnectStream);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (!hydrated) return;
    if (!user) {
      router.replace("/");
      return;
    }
    loadGamesAndSelectDefault();
    return () => {
      disconnectStream();
    };
  }, [hydrated, user, router, loadGamesAndSelectDefault, disconnectStream]);

  if (!hydrated || !user) {
    return (
      <div className="min-h-screen bg-terminal-bg flex items-center justify-center font-mono text-xs text-terminal-muted">
        INITIALIZING MTT EXCHANGE TERMINAL...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-terminal-bg flex flex-col">
      <SimulationBanner />
      <TopCommandBar />

      <main className="flex-1">
        {activeTab === "LOBBY" && <LobbyView />}

        {activeTab === "TERMINAL" && (
          <div className="p-2.5 grid grid-cols-1 lg:grid-cols-12 gap-2.5">
            {/* Left Column (3 cols): 5-Stock Market Watch + Live Simulated News Wire */}
            <div className="lg:col-span-3 space-y-2.5">
              <WatchlistPanel />
              <NewsWirePanel maxHeightClass="max-h-[410px]" />
            </div>

            {/* Center Column (6 cols): Real-Time Candlestick & Reference Price Chart + Docked Blotter */}
            <div className="lg:col-span-6 space-y-2.5">
              <CandlestickChart height={355} />
              <BottomBlotter />
            </div>

            {/* Right Column (3 cols): L2 Peer-to-Peer Order Book + 4-Intent Order Entry Ticket */}
            <div className="lg:col-span-3 space-y-2.5">
              <OrderBookLadder />
              <OrderTicket />
            </div>
          </div>
        )}

        {activeTab === "STOCK_DETAIL" && <StockDetailView />}
        {activeTab === "PORTFOLIO" && <PortfolioView />}
        {activeTab === "HISTORY" && <HistoryView />}
        {activeTab === "LEADERBOARD" && <LeaderboardView />}
      </main>
    </div>
  );
}
