import { useEffect, useState, type Dispatch } from "react";
import { api } from "../api";
import { colorById, fontFamily, useConfig } from "../config";
import { Keyboard } from "../components/Keyboard";
import { Spinner } from "../components/Chrome";
import { TagSvg } from "../components/TagSvg";
import { useIcons } from "../icons";
import type { Paths } from "../api";
import { cleanName, type Action, type State } from "../state";

type P = { state: State; dispatch: Dispatch<Action> };

function TypeScreen({ title, sub, value, dispatch }: { title: string; sub?: string; value: string; dispatch: Dispatch<Action> }) {
  const cfg = useConfig();
  const [shake, setShake] = useState(0);
  const onKey = (k: string) => {
    if (value.length >= cfg.name_max) { setShake((x) => x + 1); return; }
    dispatch({ type: "KEY", key: k, max: cfg.name_max });
  };
  return (
    <div className="screen">
      <h1>{title}</h1>
      {sub && <p className="sub">{sub}</p>}
      <div key={shake} className={shake ? "name-field shake" : "name-field"}>
        <span>{value || " "}</span><span className="caret" />
      </div>
      <div className="muted">{value.length}/{cfg.name_max}</div>
      <Keyboard onKey={onKey} onBackspace={() => dispatch({ type: "BACKSPACE" })} />
    </div>
  );
}

/** Who orders: the staff call this name with the pickup number. */
export function CustomerScreen({ state, dispatch }: P) {
  return <TypeScreen title="Wie heißt du?" sub="Damit wir wissen, wem die Anhänger gehören." value={state.customer} dispatch={dispatch} />;
}

/** Text on the tag: own name (suggested for the first tag) or someone else's. */
export function NameScreen({ state, dispatch }: P) {
  const n = state.cart.length + 1;
  return (
    <TypeScreen
      title={n === 1 ? "Was soll auf deinem Anhänger stehen?" : `Was soll auf Anhänger ${n} stehen?`}
      sub={n === 1 ? "Dein Name – oder einer für Geschwister, Oma, Papa …" : "Zum Beispiel ein Name für Geschwister, Oma, Papa …"}
      value={state.draft.name} dispatch={dispatch} />
  );
}

export function FontScreen({ state, dispatch }: P) {
  const cfg = useConfig();
  const name = cleanName(state.draft.name) || "NAME";
  return (
    <div className="screen">
      <h1>Such dir eine Schrift aus!</h1>
      <div className="grid grid-3">
        {cfg.fonts.map((f) => {
          const sel = state.draft.fontId === f.id;
          return (
            <button key={f.id} aria-label={f.label} className={sel ? "card sel" : "card"} onClick={() => dispatch({ type: "SET_FONT", fontId: f.id })}>
              <span className="font-sample" style={{ fontFamily: fontFamily(f.id), fontSize: name.length > 8 ? 40 : 54 }}>{name}</span>
              {sel && <span className="check">✓</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function ShapeScreen({ state, dispatch }: P) {
  const cfg = useConfig();
  const icons = useIcons();
  const { name, fontId, shapeId } = state.draft;
  const [fit, setFit] = useState<Record<string, boolean> | null>(null);

  useEffect(() => {
    let live = true;
    setFit(null);
    if (fontId) api.fit(cleanName(name), fontId).then((r) => live && setFit(r)).catch(() => live && setFit({}));
    return () => { live = false; };
  }, [name, fontId]);

  // a remembered shape (from the previous tag) that does not fit this name is dropped
  useEffect(() => {
    if (fit && shapeId && fit[shapeId] === false) dispatch({ type: "SET_SHAPE", shapeId: null });
  }, [fit, shapeId, dispatch]);

  // icons with the real name in the chosen font, for the shapes it fits on;
  // the sample icons stand in until they arrive
  const real = useRealIcons(cleanName(name), fontId, fit);
  const noneFits = fit && cfg.shapes.every((s) => fit[s.id] === false);
  return (
    <div className="screen">
      <h1>Welche Form soll es sein?</h1>
      {noneFits ? (
        <p className="hint">Dein Name ist für diese Schrift zu lang.<br />Geh zurück und probier eine schmalere Schrift!</p>
      ) : (
        <div className={cfg.shapes.length > 3 ? "grid grid-4" : "grid grid-3"}>
          {cfg.shapes.map((s) => {
            const ok = fit?.[s.id] !== false;
            const sel = shapeId === s.id;
            const ic = real[s.id] ?? icons[s.id];
            return (
              <button key={s.id} disabled={!ok} className={sel ? "card shape sel" : "card shape"}
                onClick={() => dispatch({ type: "SET_SHAPE", shapeId: s.id })}>
                <div className="shape-icon">
                  {ic ? <TagSvg outline={ic.outline} text={ic.text} baseHex={cfg.base_color.hex} textHex="#ffffff" /> : <Spinner />}
                </div>
                <span className="card-label">{s.label.de}</span>
                {!ok && <span className="too-long">Name zu lang</span>}
                {sel && <span className="check">✓</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

const realCache = new Map<string, Paths>();     // name|font|shape, for this page load

function useRealIcons(name: string, fontId: string | null, fit: Record<string, boolean> | null) {
  const [, bump] = useState(0);
  useEffect(() => {
    if (!fontId || !name || !fit) return;
    let live = true;
    for (const [shape, ok] of Object.entries(fit)) {
      const k = `${name}|${fontId}|${shape}`;
      if (!ok || realCache.has(k)) continue;
      api.icon(shape, name, fontId).then((p) => { realCache.set(k, p); if (live) bump((x) => x + 1); }).catch(() => {});
    }
    return () => { live = false; };
  }, [name, fontId, fit]);
  const out: Record<string, Paths> = {};
  if (fontId && fit) for (const shape of Object.keys(fit)) {
    const p = realCache.get(`${name}|${fontId}|${shape}`);
    if (p) out[shape] = p;
  }
  return out;
}

function PreviewBox({ state, dispatch }: P) {
  const cfg = useConfig();
  const d = state.draft;
  const textHex = colorById(cfg, d.colorId ?? cfg.text_colors[0].id).hex;
  return (
    <div className="preview-box">
      {d.preview ? (
        <TagSvg outline={d.preview.outline} text={d.preview.text} baseHex={cfg.base_color.hex} textHex={textHex} className="preview-svg" />
      ) : d.previewError ? (
        d.previewError === "too_long" ? <p className="hint">Der Name passt leider nicht auf diese Form.</p> : (
          <div className="hint">Das hat nicht geklappt.<br />
            <button className="btn btn-more" onClick={() => dispatch({ type: "PREVIEW_RETRY" })}>Nochmal versuchen</button>
          </div>
        )
      ) : (
        <Spinner label="Wird gebaut…" />
      )}
    </div>
  );
}

export function ColorScreen({ state, dispatch }: P) {
  const cfg = useConfig();
  return (
    <div className="screen">
      <h1>Welche Farbe soll dein Name haben?</h1>
      <p className="sub">
        Der Anhänger ist heute <b style={{ color: cfg.base_color.hex }}>{cfg.base_color.name}</b> – such dir die Farbe für deinen Namen aus!
      </p>
      <PreviewBox state={state} dispatch={dispatch} />
      <div className="colors">
        {cfg.text_colors.map((c) => {
          const sel = state.draft.colorId === c.id;
          return (
            <button key={c.id} aria-label={c.name} className={sel ? "swatch sel" : "swatch"} style={{ background: c.hex }}
              onClick={() => dispatch({ type: "SET_COLOR", colorId: c.id })}>
              <span className="swatch-label">{c.name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export { PreviewBox };
