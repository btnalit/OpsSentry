/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'obsidian-black': '#0D0D0D',
        'matrix-green': '#00FF41',
        'electric-blue': '#00A3FF',
        'alert-amber': '#FFB000',
        'crimson-red': '#FF0000',
      },
      fontFamily: {
        mono: ['Fira Code', 'JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
