/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        display: ["Fraunces", "Palatino", "Georgia", "serif"],
        sans: ["Outfit", "Avenir Next", "Segoe UI", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.4) inset, 0 16px 40px rgba(48, 32, 18, 0.06)",
      },
    },
  },
  plugins: [],
};
