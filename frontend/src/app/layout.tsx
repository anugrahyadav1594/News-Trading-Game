import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NEWS TRADING — MTT | Mumbai Trading Tournament (Quantrelic Analytics)",
  description:
    "Peer-to-peer continuous double auction stock-market simulation platform for Round 1 of the Mumbai Trading Tournament.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-terminal-bg text-terminal-text antialiased">
        {children}
      </body>
    </html>
  );
}
