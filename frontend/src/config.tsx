import { createContext, useContext } from "react";
import type { Config } from "./api";

export const ConfigContext = createContext<Config | null>(null);

export function useConfig(): Config {
  const c = useContext(ConfigContext);
  if (!c) throw new Error("config not loaded");
  return c;
}

/** CSS font-family of a tag font (registered by loadFonts). */
export const fontFamily = (id: string | null) => (id ? `"tag-${id}", "Fredoka UI", sans-serif` : `"Fredoka UI", sans-serif`);

/** Registers the tag fonts (same woff2 files the backend renders with). */
export async function loadFonts(cfg: Config): Promise<void> {
  await Promise.all(
    cfg.fonts.map(async (f) => {
      try {
        const face = new FontFace(`tag-${f.id}`, `url(${f.url})`);
        document.fonts.add(await face.load());
      } catch {
        /* missing font: card falls back to the UI font */
      }
    }),
  );
}

export const euro = (cents: number) =>
  (cents / 100).toLocaleString("de-DE", { style: "currency", currency: "EUR" });

export const colorById = (cfg: Config, id: string | null) =>
  cfg.text_colors.find((c) => c.id === id) ?? cfg.text_colors[0];

const rgb = (hex: string) => {
  const h = hex.replace("#", "");
  const v = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
};

/** Text colour for previews before the child picked one: the offered colour that
 *  stands out most on today's base colour (never white on a white tag). */
export function contrastHex(cfg: Config): string {
  const [r, g, b] = rgb(cfg.base_color.hex);
  const dist = (hex: string) => {
    const [r2, g2, b2] = rgb(hex);
    return 2 * (r - r2) ** 2 + 4 * (g - g2) ** 2 + 3 * (b - b2) ** 2;
  };
  let best = cfg.text_colors[0]?.hex;
  for (const c of cfg.text_colors) if (dist(c.hex) > dist(best)) best = c.hex;
  if (best && dist(best) > 2 * 9 * 80 ** 2) return best;      // far enough from the base
  return 0.299 * r + 0.587 * g + 0.114 * b > 140 ? "#1c1c28" : "#ffffff";
}
