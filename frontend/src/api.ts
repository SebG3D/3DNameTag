// Backend API (backend/booth/server.py). All paths are absolute: the kiosk is
// served at /kiosk/ by the same FastAPI app (in dev, Vite proxies them).

export type Color = { id: string; name: string; hex: string };
export type FontInfo = { id: string; label: string; url: string };
export type ShapeInfo = { id: string; label: { de: string; en?: string } };

export type Config = {
  event_name: string;
  base_color: { name: string; hex: string };
  text_colors: Color[];
  fonts: FontInfo[];
  shapes: ShapeInfo[];
  pricing: { free_tags: number; price_per_extra_cents: number };
  max_tags_per_order: number;
  name_max: number;
  queue_limit: number;
};

export type Status = {
  printer: string;
  current_plate: { id: number; names: string[]; status: string; remaining_min: number } | null;
  queue_length: number;
  queue_full: boolean;
  paused: boolean;
};

export type Paths = { outline: string; text: string };

export type Preview = Paths & {
  preview_id: string;
  name: string;
  size_mm: [number, number];
  estimated_min: number;
};

export type OrderResult = {
  order_id: number;
  number: number;
  tags: number;
  price_cents: number;
  needs_payment: boolean;
  eta: string;
  eta_s: number;
};

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
  }
}

async function call<T>(path: string, body?: unknown, timeoutMs = 60000): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  let r: Response;
  try {
    r = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctl.signal,
    });
  } catch {
    throw new ApiError("network", "Backend nicht erreichbar", 0);
  } finally {
    clearTimeout(timer);
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(data.error ?? `http_${r.status}`, data.message ?? data.detail ?? "", r.status);
  return data as T;
}

export const api = {
  config: () => call<Config>("/api/config", undefined, 8000),
  status: () => call<Status>("/api/status", undefined, 5000),
  fit: (name: string, font: string) => call<Record<string, boolean>>("/api/fit", { name, font }, 10000),
  icon: (shape: string) => call<Paths>(`/api/shapes/${encodeURIComponent(shape)}/icon`),
  preview: (name: string, font: string, shape: string) => call<Preview>("/api/preview", { name, font, shape }, 120000),
  order: (tags: { preview_id: string; text_color: string }[]) => call<OrderResult>("/api/orders", { tags }),
};
