import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: "#06080D",
          panel: "#0B0F17",
          elevated: "#111723",
          border: "#1C2536",
          borderBright: "#2B384E",
          muted: "#7D8CA3",
          text: "#E6ECF5",
          orange: "#FF6B00",
          orangeHover: "#FF8533",
          bid: "#10B981",
          ask: "#F43F5E",
          amber: "#F59E0B",
          cyan: "#38BDF8",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
