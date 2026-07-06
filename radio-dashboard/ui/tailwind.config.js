/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0b10",
          900: "#0f1117",
          850: "#151824",
          800: "#1b1f2e",
          700: "#272c3f",
          600: "#3a4056",
        },
        accent: {
          DEFAULT: "#7c5cff",
          soft: "#a48bff",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
