import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17201b",
        paper: "#f6f0e4",
        moss: "#546b49",
        clay: "#b56b45",
        amberline: "#d6a84f",
        tide: "#2d6f73",
        night: "#1e2a35"
      },
      boxShadow: {
        card: "0 22px 70px rgba(31, 42, 35, 0.12)"
      }
    }
  },
  plugins: []
};

export default config;
