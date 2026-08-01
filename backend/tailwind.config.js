/** @type {import('tailwindcss').Config} */

/*
 * Identidade "boudoir noir": preto com subtom quente, oxblood como cor de
 * ação, ameixa lacada como acento e champanhe para selos de confiança.
 *
 * A escolha é deliberadamente diferente do padrão do nicho (preto neutro +
 * rosa-neon). Neon grita "sex shop"; alto contraste editorial com serifa
 * didone lê como lingerie de luxo — que é o produto real aqui.
 */
module.exports = {
  darkMode: "class",
  content: ["./templates/**/*.html", "./apps/**/templates/**/*.html"],
  theme: {
    extend: {
      colors: {
        // Ação: oxblood/vinho. Menos saturado que vermelho puro, sustenta
        // botão grande sem cansar a vista numa página escura.
        brand: {
          DEFAULT: "#c01844",
          light: "#e0295c",
          dark: "#8e0f31",
          darker: "#5c0a20",
        },
        // Fundo: preto com subtom vinho (nunca cinza neutro).
        surface: {
          DEFAULT: "#0b0709",
          alt: "#120c10",
          card: "#180f14",
          raised: "#20141a",
          border: "#2e1c25",
        },
        accent: {
          // Ameixa lacada — segunda cor da marca, usada em gradiente e selos.
          orchid: "#8a3fa8",
          orchiddark: "#5a2470",
          // Champanhe — reputação, verificação, destaque pago.
          gold: "#d9b26b",
          blush: "#f4d3dc",
        },
      },
      fontFamily: {
        // UI: grotesk com personalidade (não é Inter/Poppins do resto do nicho).
        sans: ["Space Grotesk", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        // Display: didone de alto contraste — editorial de moda íntima.
        display: ["Bodoni Moda", "ui-serif", "Georgia", "serif"],
      },
      letterSpacing: {
        tightest: "-0.045em",
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.25rem",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(192,24,68,0.35), 0 14px 34px -12px rgba(138,63,168,0.55)",
        "glow-orchid": "0 12px 36px -12px rgba(138,63,168,0.6)",
        lift: "0 18px 40px -20px rgba(0,0,0,0.9)",
      },
      backgroundImage: {
        "gradient-brand": "linear-gradient(115deg, #8a3fa8 0%, #c01844 65%, #e0295c 100%)",
        "gradient-noir":
          "linear-gradient(180deg, rgba(138,63,168,0.16) 0%, rgba(192,24,68,0.06) 40%, transparent 75%)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up .35s ease-out both",
      },
    },
  },
  plugins: [],
};
