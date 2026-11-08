import { useEffect, useMemo, useState, type Dispatch } from "react";
import { api, ApiError, type Preview } from "../api";
import { colorById, euro, fontFamily, useConfig } from "../config";
import { Nav, STEP_COLORS } from "../components/Chrome";
import { TagSvg } from "../components/TagSvg";
import { type Action, type CartItem, type State } from "../state";
import { PreviewBox } from "./Wizard";

type P = { state: State; dispatch: Dispatch<Action> };

const ERRORS: Record<string, string> = {
  queue_full: "Die Warteschlange ist gerade voll. Bitte frag am Stand nach!",
  network: "Keine Verbindung zum Drucker-Computer. Bitte hol einen Erwachsenen.",
};

export function ReviewScreen({ state, dispatch }: P) {
  const cfg = useConfig();
  const d = state.draft;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const n = state.cart.length + 1;
  const { free_tags, price_per_extra_cents: each } = cfg.pricing;
  const price = Math.max(0, n - free_tags) * each;
  const canAdd = n < cfg.max_tags_per_order;
  const ready = !!d.preview && !busy;

  const submit = async () => {
    if (!d.preview || !d.colorId) return;
    setBusy(true);
    setError(null);
    const items = (cart: CartItem[], cur: Preview) => [
      ...cart.map((c) => ({ preview_id: c.preview.preview_id, text_color: c.colorId })),
      { preview_id: cur.preview_id, text_color: d.colorId! },
    ];
    try {
      let cart = state.cart, cur = d.preview;
      try {
        dispatch({ type: "ORDER_OK", order: await api.order(items(cart, cur), state.customer) });
        return;
      } catch (e) {
        if (!(e instanceof ApiError) || e.code !== "preview_expired") throw e;
      }
      // previews time out after 10 min on the server: render them again and retry once
      cart = await Promise.all(cart.map(async (c) => ({ ...c, preview: await api.preview(c.name, c.fontId, c.shapeId) })));
      cur = await api.preview(cur.name, d.fontId!, d.shapeId!);
      dispatch({ type: "REFRESH_PREVIEWS", cart, draft: cur });
      dispatch({ type: "ORDER_OK", order: await api.order(items(cart, cur), state.customer) });
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "x";
      setError(ERRORS[code] ?? "Das hat leider nicht geklappt. Versuch es nochmal!");
      setBusy(false);
    }
  };

  return (
    <div className="screen review">
      <h1>{n === 1 ? "So sieht dein Anhänger aus!" : `Anhänger ${n}`}</h1>
      <div className="review-main">
        <div className="review-tag">
          <PreviewBox state={state} dispatch={dispatch} />
          <div className="facts">
            <span className="fact" style={{ fontFamily: fontFamily(d.fontId) }}>{d.preview?.name ?? d.name}</span>
            <span className="fact">{cfg.shapes.find((s) => s.id === d.shapeId)?.label.de}</span>
            <span className="fact"><i className="chip-dot" style={{ background: colorById(cfg, d.colorId).hex }} />{colorById(cfg, d.colorId).name}</span>
          </div>
        </div>
        {state.cart.length > 0 && (
          <div className="cart">
            <div className="cart-title">Schon dabei:</div>
            {state.cart.map((c, i) => (
              <div key={i} className="cart-item">
                <TagSvg outline={c.preview.outline} text={c.preview.text} baseHex={cfg.base_color.hex} textHex={colorById(cfg, c.colorId).hex} className="cart-svg" />
                <button className="btn-x" aria-label="Entfernen" onClick={() => dispatch({ type: "REMOVE_ITEM", index: i })}>✕</button>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="price-line">
        {price === 0 ? "Gratis! 🎁"
          : free_tags > 0 ? `${Math.min(n, free_tags)} gratis + ${n - free_tags} × ${euro(each)} = ${euro(price)} – bitte am Stand bezahlen`
          : `${n} × ${euro(each)} = ${euro(price)} – bitte am Stand bezahlen`}
      </div>
      {error && <div className="error-line">{error}</div>}
      <Nav
        onBack={busy ? undefined : () => dispatch({ type: "GOTO", screen: "color" })}
        middle={canAdd && !busy ? (
          <button className="btn btn-more" disabled={!d.preview} onClick={() => dispatch({ type: "ADD_ANOTHER" })}>
            + Noch einen Anhänger{each > 0 && n + 1 > free_tags ? ` (${euro(each)})` : ""}
          </button>
        ) : undefined}
        onNext={submit}
        nextDisabled={!ready}
        nextLabel={busy ? "Einen Moment…" : n === 1 ? "🖨️ Drucken!" : `🖨️ Alle ${n} drucken!`}
      />
    </div>
  );
}

export function DoneScreen({ state, dispatch }: P) {
  const cfg = useConfig();
  const o = state.order;
  useEffect(() => {
    const id = setTimeout(() => dispatch({ type: "RESET" }), o?.needs_payment ? 40000 : 25000);
    return () => clearTimeout(id);
  }, [dispatch, o]);
  const confetti = useMemo(() => Array.from({ length: 60 }, (_, i) => ({
    left: Math.random() * 100, delay: Math.random() * 2.5, dur: 2.5 + Math.random() * 2,
    color: [...STEP_COLORS, "#EC407A"][i % 6], rot: Math.random() * 360,
  })), []);
  if (!o) return null;
  return (
    <div className="screen done">
      {confetti.map((c, i) => (
        <span key={i} className="confetti" style={{ left: `${c.left}%`, background: c.color, animationDuration: `${c.dur}s`, animationDelay: `${c.delay}s`, rotate: `${c.rot}deg` }} />
      ))}
      <h1>🎉 Super{o.customer ? `, ${o.customer}` : ""}!</h1>
      <p className="done-text">Deine Nummer:</p>
      <div className="done-num">{o.number}</div>
      <p className="done-text">Fertig ungefähr um <b>{o.eta} Uhr</b>.</p>
      {o.needs_payment ? (
        <p className="pay-note">Bitte jetzt am Stand <b>{euro(o.price_cents)}</b> bezahlen und deine Nummer sagen.{cfg.pricing.free_tags > 0 && <><br />Dein erster Anhänger ist schon in der Warteschlange!</>}</p>
      ) : (
        <p className="muted big">Merk dir deine Nummer und sag sie am Stand!</p>
      )}
      <button className="btn btn-go" onClick={() => dispatch({ type: "RESET" })}>Fertig</button>
    </div>
  );
}

export function OfflineScreen() {
  return (
    <div className="screen center">
      <h1>Kleine Pause ☕</h1>
      <p className="sub">Der Anhänger-Drucker macht gerade Pause.<br />Bitte hol einen Erwachsenen 🙂</p>
      <div className="muted">Ich versuche es automatisch weiter …</div>
    </div>
  );
}
