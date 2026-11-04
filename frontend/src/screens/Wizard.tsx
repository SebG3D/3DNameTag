import { useEffect, useState, type Dispatch } from "react";
import { api } from "../api";
import { colorById, fontFamily, useConfig } from "../config";
import { Keyboard } from "../components/Keyboard";
import { Spinner } from "../components/Chrome";
import { TagSvg } from "../components/TagSvg";
import { useIcons } from "../icons";
import { cleanName, type Action, type State } from "../state";

type P = { state: State; dispatch: Dispatch<Action> };

export function NameScreen({ state, dispatch }: P) {
  const cfg = useConfig();
  const [shake, setShake] = useState(0);
  const name = state.draft.name;
  const n = state.cart.length + 1;
  const onKey = (k: string) => {
    if (name.length >= cfg.name_max) { setShake((x) => x + 1); return; }
    dispatch({ type: "KEY", key: k, max: cfg.name_max });
  };
  return (
    <div className="screen">
      <h1>{n === 1 ? "Wie heißt du?" : `Welcher Name kommt auf Anhänger ${n}?`}</h1>
      <div key={shake} className={shake ? "name-field shake" : "name-field"}>
        <span>{name || " "}</span><span className="caret" />
      </div>
      <div className="muted">{name.length}/{cfg.name_max}</div>
      <Keyboard onKey={onKey} onBackspace={() => dispatch({ type: "BACKSPACE" })} />
    </div>
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
            <button key={f.id} className={sel ? "card sel" : "card"} onClick={() => dispatch({ type: "SET_FONT", fontId: f.id })}>
              <span className="font-sample" style={{ fontFamily: fontFamily(f.id), fontSize: name.length > 8 ? 40 : 54 }}>{name}</span>
              <span className="card-label">{f.label}</span>
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
            const ic = icons[s.id];
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
