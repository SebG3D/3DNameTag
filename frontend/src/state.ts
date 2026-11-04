import type { OrderResult, Preview } from "./api";

export const NAME_RE = /^[A-Z0-9ÄÖÜß\- ]$/;

export type Screen = "attract" | "name" | "font" | "shape" | "color" | "review" | "done";
/** Wizard steps with progress dots (attract/done have none). */
export const STEPS: Screen[] = ["name", "font", "shape", "color", "review"];

export type Draft = {
  name: string;
  fontId: string | null;
  shapeId: string | null;
  colorId: string | null;
  preview: Preview | null;
  previewKey: string | null;      // name|font|shape the preview belongs to
  previewError: string | null;
};

export type CartItem = {
  name: string;
  fontId: string;
  shapeId: string;
  colorId: string;
  preview: Preview;
};

export type State = {
  screen: Screen;
  draft: Draft;
  cart: CartItem[];          // finished tags of this order (without the draft)
  order: OrderResult | null;
};

const emptyDraft: Draft = {
  name: "", fontId: null, shapeId: null, colorId: null,
  preview: null, previewKey: null, previewError: null,
};
export const initialState: State = { screen: "attract", draft: emptyDraft, cart: [], order: null };

export const cleanName = (n: string) => n.trim().replace(/ +/g, " ");
export const previewKey = (d: Draft) =>
  d.fontId && d.shapeId && cleanName(d.name) ? `${cleanName(d.name)}|${d.fontId}|${d.shapeId}` : null;

export type Action =
  | { type: "START" }
  | { type: "GOTO"; screen: Screen }
  | { type: "NEXT" }
  | { type: "BACK" }
  | { type: "KEY"; key: string; max: number }
  | { type: "BACKSPACE" }
  | { type: "SET_FONT"; fontId: string }
  | { type: "SET_SHAPE"; shapeId: string | null }
  | { type: "SET_COLOR"; colorId: string }
  | { type: "PREVIEW_START"; key: string }
  | { type: "PREVIEW_OK"; key: string; preview: Preview }
  | { type: "PREVIEW_FAIL"; key: string; code: string }
  | { type: "PREVIEW_RETRY" }
  | { type: "ADD_ANOTHER" }
  | { type: "UNDO_ADD" }
  | { type: "REMOVE_ITEM"; index: number }
  | { type: "REFRESH_PREVIEWS"; cart: CartItem[]; draft: Preview }
  | { type: "ORDER_OK"; order: OrderResult }
  | { type: "RESET" };

const move = (s: State, d: 1 | -1): Screen => {
  const i = STEPS.indexOf(s.screen);
  return i < 0 ? s.screen : STEPS[Math.max(0, Math.min(STEPS.length - 1, i + d))];
};

export function canGoNext(s: State): boolean {
  const d = s.draft;
  switch (s.screen) {
    case "name": return cleanName(d.name).length > 0;
    case "font": return !!d.fontId;
    case "shape": return !!d.shapeId;
    case "color": return !!d.colorId;
    default: return false;
  }
}

export function reducer(s: State, a: Action): State {
  const d = s.draft;
  switch (a.type) {
    case "START": return { ...initialState, screen: "name" };
    case "GOTO": return { ...s, screen: a.screen };
    case "NEXT": return canGoNext(s) ? { ...s, screen: move(s, 1) } : s;
    case "BACK": return { ...s, screen: move(s, -1) };
    case "KEY": {
      const k = a.key.length === 1 && a.key !== "ß" ? a.key.toUpperCase() : a.key;
      if (!NAME_RE.test(k) || d.name.length >= a.max) return s;
      if (k === " " && (d.name === "" || d.name.endsWith(" "))) return s;
      return { ...s, draft: { ...d, name: d.name + k } };
    }
    case "BACKSPACE": return { ...s, draft: { ...d, name: d.name.slice(0, -1) } };
    case "SET_FONT": return { ...s, draft: { ...d, fontId: a.fontId } };
    case "SET_SHAPE": return { ...s, draft: { ...d, shapeId: a.shapeId } };
    case "SET_COLOR": return { ...s, draft: { ...d, colorId: a.colorId } };
    case "PREVIEW_START":
      return { ...s, draft: { ...d, previewKey: a.key, preview: null, previewError: null } };
    case "PREVIEW_OK":
      return previewKey(d) === a.key ? { ...s, draft: { ...d, previewKey: a.key, preview: a.preview, previewError: null } } : s;
    case "PREVIEW_FAIL":
      return previewKey(d) === a.key ? { ...s, draft: { ...d, previewKey: a.key, preview: null, previewError: a.code } } : s;
    case "PREVIEW_RETRY": return { ...s, draft: { ...d, previewKey: null, previewError: null } };
    case "ADD_ANOTHER": {
      if (!d.preview || !d.fontId || !d.shapeId || !d.colorId) return s;
      const item: CartItem = { name: d.preview.name, fontId: d.fontId, shapeId: d.shapeId, colorId: d.colorId, preview: d.preview };
      // keep font/shape/colour as defaults for the next tag, only the name is new
      return { ...s, cart: [...s.cart, item], draft: { ...emptyDraft, fontId: d.fontId, shapeId: d.shapeId, colorId: d.colorId }, screen: "name" };
    }
    case "UNDO_ADD": {
      // back from the name screen of an extra tag: the last tag becomes the draft again
      const last = s.cart[s.cart.length - 1];
      if (!last) return initialState;
      const draft: Draft = { ...emptyDraft, name: last.name, fontId: last.fontId, shapeId: last.shapeId, colorId: last.colorId, preview: last.preview };
      return { ...s, cart: s.cart.slice(0, -1), draft: { ...draft, previewKey: previewKey(draft) }, screen: "review" };
    }
    case "REMOVE_ITEM": return { ...s, cart: s.cart.filter((_, i) => i !== a.index) };
    case "REFRESH_PREVIEWS": return { ...s, cart: a.cart, draft: { ...d, preview: a.draft } };
    case "ORDER_OK": return { ...s, order: a.order, screen: "done" };
    case "RESET": return initialState;
  }
}
