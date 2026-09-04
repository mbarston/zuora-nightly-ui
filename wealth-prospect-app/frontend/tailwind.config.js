/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#0b1220", 900: "#111a2e", 800: "#1a2540", 700: "#273354" },
        brand: { 50: "#eef4ff", 100: "#dbe6ff", 300: "#93b4ff", 500: "#3b6cf6", 600: "#2f57d6", 700: "#2546ad" },
        signal: { green: "#16a34a", amber: "#d97706", red: "#dc2626", violet: "#7c3aed" },
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.1)" },
    },
  },
  plugins: [],
};
