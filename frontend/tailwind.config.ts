import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#07111f",
        mist: "#e7edf7",
        cyan: "#5eead4",
        coral: "#fb7185",
        amber: "#fbbf24",
        cobalt: "#60a5fa",
      },
      boxShadow: {
        atmospheric: "0 24px 80px rgba(2, 6, 23, 0.45)",
      },
      fontFamily: {
        sans: ["Trebuchet MS", "Segoe UI Variable", "Segoe UI", "sans-serif"],
        display: ["Georgia", "Cambria", "serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
