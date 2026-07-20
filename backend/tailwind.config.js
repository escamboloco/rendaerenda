/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./templates/**/*.html", "./apps/**/templates/**/*.html"],
  theme: {
    extend: {
      colors: {
        // Vermelho = paixao/acao (CTAs, precos, links). Violeta = base do
        // site (fundo, superficies, bordas) - sedutor sem ser gritante.
        brand: {
          DEFAULT: "#e0243f",
          light: "#f0455f",
          dark: "#a8172f",
          darker: "#711022",
        },
        surface: {
          DEFAULT: "#0e0a14",
          alt: "#170f21",
          card: "#1c1329",
          border: "#2c2038",
        },
        accent: {
          gold: "#e8b34d",
          violet: "#7c4dbf",
          violetdark: "#4c2d78",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.25rem",
      },
      boxShadow: {
        // Anel vermelho + halo violeta - da profundidade "sedutora" sem
        // precisar de gradiente em todo canto.
        glow: "0 0 0 1px rgba(224,36,63,0.30), 0 10px 28px -8px rgba(124,77,191,0.45)",
        "glow-violet": "0 10px 32px -10px rgba(124,77,191,0.55)",
      },
      backgroundImage: {
        "gradient-brand": "linear-gradient(135deg, #7c4dbf 0%, #e0243f 100%)",
      },
    },
  },
  plugins: [],
};
