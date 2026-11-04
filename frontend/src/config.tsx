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
