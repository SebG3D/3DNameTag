import { useEffect, useState } from "react";
import { api, type Paths } from "./api";

// Shape icons (outline + sample name), fetched once per page load.
const icons: Record<string, Paths> = {};
const listeners = new Set<() => void>();
let loading: Promise<void> | null = null;

export function preloadIcons(shapeIds: string[]): Promise<void> {
  loading ??= (async () => {
    for (const id of shapeIds) {           // one after another: OpenSCAD on the Pi
      for (let attempt = 0; attempt < 3 && !icons[id]; attempt++) {
        try {
          icons[id] = await api.icon(id);
          listeners.forEach((l) => l());
        } catch {
          await new Promise((r) => setTimeout(r, 2000));
        }
      }
    }
  })();
  return loading;
}

export function useIcons(): Record<string, Paths> {
  const [, bump] = useState(0);
  useEffect(() => {
    const l = () => bump((n) => n + 1);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
  return icons;
}
