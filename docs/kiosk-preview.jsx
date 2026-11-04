import { useEffect, useMemo, useReducer, useRef, useState } from "react";

/* ============================================================
   Kiosk "Namens-Anhänger-Drucker" — M1-Vorschau (ohne Backend)
   Einzeldatei-Version des Vite-Projekts zum Antippen im Chat.
   Schriften sind hier nur ANGENÄHERT (echte Fonts im Projekt).
   ============================================================ */

const NAME_MAX = 12;
const NAME_RE = /^[A-Z0-9ÄÖÜß\- ]$/;
const STEP_COLORS = ["#E53935", "#FB8C00", "#FDD835", "#43A047", "#1E88E5"];

const CONFIG = {
  base_color: { name: "Blau", hex: "#1565C0" },
  text_colors: [
    { id: "red", name: "Rot", hex: "#E53935" },
    { id: "yellow", name: "Gelb", hex: "#FDD835" },
    { id: "green", name: "Grün", hex: "#43A047" },
    { id: "orange", name: "Orange", hex: "#FB8C00" },
    { id: "white", name: "Weiß", hex: "#FAFAFA" },
    { id: "pink", name: "Pink", hex: "#EC407A" },
  ],
  shapes: ["stadium", "heart", "bone"],
  event_name: "Schulfest 2026",
};

// Angenäherte Darstellung der 6 echten Fonts (im Projekt: Fontsource .woff2)
const FONTS = [
  { id: "baloo", label: "Baloo 2", style: { fontFamily: "'Comic Sans MS', system-ui", fontWeight: 800 } },
  { id: "bangers", label: "Bangers", style: { fontFamily: "Impact, sans-serif", letterSpacing: 3 } },
  { id: "fredoka", label: "Fredoka", style: { fontFamily: "'Trebuchet MS', sans-serif", fontWeight: 700 } },
  { id: "pacifico", label: "Pacifico", style: { fontFamily: "'Brush Script MT', cursive", fontWeight: 400 } },
  { id: "titan", label: "Titan One", style: { fontFamily: "'Arial Black', sans-serif", fontWeight: 900 } },
  { id: "chewy", label: "Chewy", style: { fontFamily: "'Comic Sans MS', cursive", fontStyle: "italic", fontWeight: 700 } },
];
const fontById = (id) => FONTS.find((f) => f.id === id) ?? FONTS[0];
const SHAPE_LABEL = { stadium: "Tag", heart: "Herz", bone: "Knochen" };

/* ---------- Reducer (identisch zum Projekt) ---------- */
const initialState = {
  screen: 0, name: "", fontId: null, shape: null, textColorId: null,
  preview: null, previewError: false, job: null,
};
function reducer(s, a) {
  switch (a.type) {
    case "START": return { ...initialState, screen: 1 };
    case "NEXT": {
      const n = Math.min(6, s.screen + 1);
      return n === 5 ? { ...s, screen: 5, preview: null, previewError: false } : { ...s, screen: n };
    }
    case "BACK": return s.screen <= 1 ? s : { ...s, screen: s.screen - 1 };
    case "GOTO": return { ...s, screen: a.screen };
    case "KEY_PRESS": {
      const k = a.key.toUpperCase();
      if (!NAME_RE.test(k) || s.name.length >= NAME_MAX) return s;
      return { ...s, name: s.name + k };
    }
    case "BACKSPACE": return { ...s, name: s.name.slice(0, -1) };
    case "SET_FONT": return { ...s, fontId: a.fontId };
    case "SET_SHAPE": return { ...s, shape: a.shape };
    case "SET_COLOR": return { ...s, textColorId: a.colorId };
    case "PREVIEW_OK": return { ...s, preview: a.preview, previewError: false };
    case "CONFIRM_OK": return { ...s, job: a.job, screen: 6 };
    case "RESET": case "TIMEOUT": return initialState;
    default: return s;
  }
}
const canGoNext = (s) =>
  (s.screen === 1 && s.name.trim().length >= 1) ||
  (s.screen === 2 && !!s.fontId) ||
  (s.screen === 3 && !!s.shape) ||
  (s.screen === 4 && !!s.textColorId);

/* ---------- Mock-API ---------- */
let mockQueue = 2, mockJob = 4;
const mockPreview = (name) =>
  new Promise((res) =>
    setTimeout(() => res({ preview_id: "p_" + Date.now(), estimated_min: 8 + Math.min(6, Math.ceil(name.length / 2)) }), 2200)
  );
const mockConfirm = () =>
  new Promise((res) =>
    setTimeout(() => {
      mockQueue += 1; mockJob += 1;
      const eta = new Date(Date.now() + mockQueue * 12 * 60000);
      res({ job_id: mockJob, queue_position: mockQueue, eta: eta.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) });
    }, 500)
  );

/* ---------- SVG-Tag-Vorschau ---------- */
function TagPreview({ name, fontId, shape, baseHex, textHex, spin }) {
  const display = (name || "").trim() || "NAME";
  const w = Math.max(150, 60 + display.length * 34);
  const vbH = shape === "stadium" ? 140 : 190;
  const vbW = w + 80, h = 96, cy = vbH / 2;
  const stroke = "rgba(0,0,0,.15)";
  return (
    <svg viewBox={`0 0 ${vbW} ${vbH}`} style={{ width: "100%", filter: "drop-shadow(0 8px 14px rgba(0,0,0,.18))", animation: spin ? "sway 6s ease-in-out infinite" : "none", transformOrigin: "8% 50%" }}>
      {shape !== "bone" && <rect x={20} y={(vbH - h) / 2} width={w + 40} height={h} rx={h / 2} fill={baseHex} stroke={stroke} strokeWidth={3} />}
      {shape === "heart" && (
        <path transform={`translate(${w + 70}, ${cy - 12}) scale(1.6)`} d="M0 8 C0 2 5 -2 10 1 C15 -2 20 2 20 8 C20 14 10 22 10 22 C10 22 0 14 0 8 Z" fill={baseHex} stroke={stroke} strokeWidth={2} />
      )}
      {shape === "bone" && (
        <>
          <rect x={44} y={cy - h / 2 + 14} width={w} height={h - 28} rx={24} fill={baseHex} stroke={stroke} strokeWidth={3} />
          {[44, 44 + w].map((x) => (
            <g key={x}>
              <circle cx={x} cy={cy - 22} r={26} fill={baseHex} stroke={stroke} strokeWidth={3} />
              <circle cx={x} cy={cy + 22} r={26} fill={baseHex} stroke={stroke} strokeWidth={3} />
            </g>
          ))}
        </>
      )}
      <circle cx={40} cy={cy} r={9} fill="#fff" stroke="rgba(0,0,0,.25)" strokeWidth={3} />
      <text x={40 + (w + 20) / 2 + 10} y={cy} textAnchor="middle" dominantBaseline="central" fill={textHex} stroke="rgba(0,0,0,.25)" strokeWidth={0.8} style={{ ...fontById(fontId).style, fontSize: 52, paintOrder: "stroke" }}>
        {display}
      </text>
    </svg>
  );
}

/* ---------- Tastatur ---------- */
const ROWS = [
  ["1","2","3","4","5","6","7","8","9","0","-"],
  ["Q","W","E","R","T","Z","U","I","O","P","Ü"],
  ["A","S","D","F","G","H","J","K","L","Ö","Ä"],
  ["Y","X","C","V","B","N","M","ß"],
];
function Keyboard({ onKey, onBackspace }) {
  const rep = useRef({});
  const start = () => {
    onBackspace();
    rep.current.t = setTimeout(() => { rep.current.i = setInterval(onBackspace, 80); }, 400);
  };
  const stop = () => { clearTimeout(rep.current.t); clearInterval(rep.current.i); };
  const key = (base) => ({
    minWidth: 44, minHeight: 52, borderRadius: 12, background: "#f2f2f8",
    border: "2px solid #d8d8e4", fontSize: 20, fontWeight: 600, ...base,
  });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "center", width: "100%" }}>
      {ROWS.map((row, i) => (
        <div key={i} style={{ display: "flex", gap: 6, flexWrap: "nowrap" }}>
          {row.map((k) => (
            <button key={k} style={key()} onPointerDown={(e) => { e.preventDefault(); onKey(k); }}>{k}</button>
          ))}
          {i === 3 && (
            <button style={key({ minWidth: 70, background: "#fde3e3", borderColor: "#f3bcbc" })}
              onPointerDown={(e) => { e.preventDefault(); start(); }}
              onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop}>⌫</button>
          )}
        </div>
      ))}
      <button style={key({ minWidth: 260 })} onPointerDown={(e) => { e.preventDefault(); onKey(" "); }}>Leertaste</button>
    </div>
  );
}

/* ---------- Bausteine ---------- */
const btn = (bg, fg, extra) => ({
  minHeight: 60, padding: "12px 28px", borderRadius: 18, fontSize: 22,
  fontWeight: 700, border: "none", background: bg, color: fg, cursor: "pointer", ...extra,
});
function Nav({ onBack, onNext, disabled, label }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", width: "100%", paddingTop: 8 }}>
      {onBack ? <button style={btn("#e4e4ec", "#55555f")} onClick={onBack}>← Zurück</button> : <span />}
      {onNext ? <button style={btn("#2e9e44", "#fff", { opacity: disabled ? 0.35 : 1 })} disabled={disabled} onClick={onNext}>{label ?? "Weiter"} →</button> : <span />}
    </div>
  );
}
function Dots({ step }) {
  return (
    <div style={{ display: "flex", justifyContent: "center", gap: 12, padding: "4px 0" }}>
      {STEP_COLORS.map((c, i) => {
        const n = i + 1;
        return <span key={i} style={{ width: 18, height: 18, borderRadius: "50%", transition: "all .2s", background: n <= step ? c : "#e4e4ec", opacity: n < step ? 0.55 : 1, transform: n === step ? "scale(1.35)" : "none" }} />;
      })}
    </div>
  );
}

/* ---------- Screens ---------- */
function Attract({ onStart }) {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 28 }}>
      <div style={{ fontSize: 20, color: "#55555f" }}>{CONFIG.event_name}</div>
      <div style={{ width: "min(80%, 480px)" }}>
        <TagPreview name="EMMA" fontId="baloo" shape="stadium" baseHex={CONFIG.base_color.hex} textHex="#E53935" spin />
      </div>
      <button style={btn("#2e9e44", "#fff", { fontSize: 26, padding: "20px 36px", borderRadius: 28, animation: "pulse 1.6s ease-in-out infinite", boxShadow: "0 10px 30px rgba(46,158,68,.35)" })} onClick={onStart}>
        Tippe hier und mach deinen Anhänger!
      </button>
      <div style={{ fontSize: 17, color: "#55555f" }}>Gerade druckt: LEON · {mockQueue} warten</div>
    </div>
  );
}

function NameScreen({ state, dispatch }) {
  const [shake, setShake] = useState(0);
  const onKey = (k) => {
    if (state.name.length >= NAME_MAX) { setShake((x) => x + 1); return; }
    dispatch({ type: "KEY_PRESS", key: k });
  };
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
      <h1 style={{ fontSize: 28, color: "var(--accent)" }}>Wie heißt du?</h1>
      <div key={shake} style={{ fontSize: 44, fontWeight: 700, letterSpacing: 3, minHeight: 60, display: "flex", alignItems: "center", borderBottom: "5px solid var(--accent)", padding: "0 16px 4px", whiteSpace: "pre", animation: shake ? "shake .3s" : "none" }}>
        {state.name || "\u00A0"}
        <span style={{ width: 4, height: 40, background: "var(--accent)", marginLeft: 6, animation: "blink 1s step-start infinite" }} />
      </div>
      <div style={{ fontSize: 16, color: "#55555f" }}>{state.name.length}/{NAME_MAX}</div>
      <Keyboard onKey={onKey} onBackspace={() => dispatch({ type: "BACKSPACE" })} />
    </div>
  );
}

function FontScreen({ state, dispatch }) {
  const name = state.name.trim() || "NAME";
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
      <h1 style={{ fontSize: 28, color: "var(--accent)" }}>Such dir eine Schrift aus!</h1>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 14, width: "100%" }}>
        {FONTS.map((f) => {
          const sel = state.fontId === f.id;
          return (
            <button key={f.id} onClick={() => dispatch({ type: "SET_FONT", fontId: f.id })}
              style={{ position: "relative", background: "#fff", border: `4px solid ${sel ? "var(--accent)" : "#e0e0ea"}`, borderRadius: 18, padding: "16px 8px 10px", display: "flex", flexDirection: "column", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <span style={{ ...f.style, fontSize: 26, whiteSpace: "nowrap", overflow: "hidden", maxWidth: "100%" }}>{name}</span>
              <span style={{ fontSize: 15, color: "#55555f" }}>{f.label}</span>
              {sel && <span style={{ position: "absolute", top: -12, right: -12, width: 34, height: 34, borderRadius: "50%", background: "var(--accent)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>✓</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ShapeScreen({ state, dispatch }) {
  const icons = {
    stadium: <svg viewBox="0 0 120 60" width="100"><rect x="4" y="8" width="112" height="44" rx="22" fill="currentColor" /><circle cx="26" cy="30" r="7" fill="#fff" /></svg>,
    heart: <svg viewBox="0 0 120 100" width="100"><path d="M60 90 C20 60 8 38 20 22 C32 8 52 12 60 28 C68 12 88 8 100 22 C112 38 100 60 60 90 Z" fill="currentColor" /><circle cx="60" cy="34" r="7" fill="#fff" /></svg>,
    bone: <svg viewBox="0 0 120 60" width="100"><rect x="24" y="20" width="72" height="20" rx="10" fill="currentColor" /><circle cx="24" cy="18" r="14" fill="currentColor" /><circle cx="24" cy="42" r="14" fill="currentColor" /><circle cx="96" cy="18" r="14" fill="currentColor" /><circle cx="96" cy="42" r="14" fill="currentColor" /><circle cx="30" cy="30" r="6" fill="#fff" /></svg>,
  };
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
      <h1 style={{ fontSize: 28, color: "var(--accent)" }}>Welche Form soll es sein?</h1>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, width: "100%" }}>
        {CONFIG.shapes.map((sh) => {
          const sel = state.shape === sh;
          return (
            <button key={sh} onClick={() => dispatch({ type: "SET_SHAPE", shape: sh })}
              style={{ position: "relative", color: "var(--accent)", background: "#fff", border: `4px solid ${sel ? "var(--accent)" : "#e0e0ea"}`, borderRadius: 18, padding: "18px 8px 10px", display: "flex", flexDirection: "column", alignItems: "center", gap: 8, cursor: "pointer" }}>
              {icons[sh]}
              <span style={{ fontSize: 17, color: "#55555f" }}>{SHAPE_LABEL[sh]}</span>
              {sel && <span style={{ position: "absolute", top: -12, right: -12, width: 34, height: 34, borderRadius: "50%", background: "var(--accent)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>✓</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ColorScreen({ state, dispatch }) {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
      <h1 style={{ fontSize: 28, color: "var(--accent)" }}>Welche Farbe soll dein Name haben?</h1>
      <p style={{ fontSize: 18, textAlign: "center" }}>
        Die Grundfarbe ist heute <strong style={{ color: CONFIG.base_color.hex }}>{CONFIG.base_color.name}</strong> — such dir die Farbe für deinen Namen aus!
      </p>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", justifyContent: "center" }}>
        {CONFIG.text_colors.map((c) => {
          const sel = state.textColorId === c.id;
          return (
            <button key={c.id} aria-label={c.name} onClick={() => dispatch({ type: "SET_COLOR", colorId: c.id })}
              style={{ width: 74, height: 74, borderRadius: "50%", background: c.hex, border: `5px solid ${sel ? "#1c1c28" : "rgba(0,0,0,.15)"}`, transform: sel ? "scale(1.12)" : "none", transition: "all .15s", cursor: "pointer", color: "#fff", fontSize: 30, textShadow: "0 2px 6px rgba(0,0,0,.6)" }}>
              {sel ? "✓" : ""}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PreviewScreen({ state, dispatch }) {
  const [confirming, setConfirming] = useState(false);
  const requested = useRef(false);
  const color = CONFIG.text_colors.find((c) => c.id === state.textColorId) ?? CONFIG.text_colors[0];

  useEffect(() => {
    if (requested.current || state.preview) return;
    requested.current = true;
    mockPreview(state.name.trim()).then((r) =>
      dispatch({ type: "PREVIEW_OK", preview: { id: r.preview_id, etaMin: r.estimated_min } })
    );
  }, []);

  const confirm = async () => {
    setConfirming(true);
    const r = await mockConfirm();
    dispatch({ type: "CONFIRM_OK", job: { id: r.job_id, position: r.queue_position, eta: r.eta } });
  };

  const facts = [state.name.trim(), fontById(state.fontId).label, SHAPE_LABEL[state.shape ?? "stadium"], color.name];
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <h1 style={{ fontSize: 28, color: "var(--accent)" }}>So sieht dein Anhänger aus!</h1>
      <div style={{ position: "relative", width: "100%", background: "#f4f6fb", borderRadius: 18, padding: 18, display: "flex", justifyContent: "center" }}>
        <TagPreview name={state.name} fontId={state.fontId} shape={state.shape ?? "stadium"} baseHex={CONFIG.base_color.hex} textHex={color.hex} />
        {!state.preview && (
          <div style={{ position: "absolute", inset: 0, background: "rgba(255,255,255,.75)", borderRadius: 18, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, fontSize: 20, fontWeight: 600 }}>
            <div style={{ width: 44, height: 44, border: "6px solid #e4e4ec", borderTopColor: "var(--accent)", borderRadius: "50%", animation: "spin .9s linear infinite" }} />
            Wird gebaut…
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
        {facts.map((f, i) => <span key={i} style={{ background: "#f2f2f8", borderRadius: 12, padding: "6px 14px", fontSize: 17 }}>{f}</span>)}
        {state.preview && <span style={{ background: "#f2f2f8", borderRadius: 12, padding: "6px 14px", fontSize: 17 }}>Druckzeit: ca. {state.preview.etaMin} Min</span>}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
        <button style={btn("#e4e4ec", "#55555f")} onClick={() => dispatch({ type: "GOTO", screen: 1 })}>Nochmal ändern</button>
        <button style={btn("#2e9e44", "#fff", { fontSize: 24, opacity: state.preview && !confirming ? 1 : 0.35 })} disabled={!state.preview || confirming} onClick={confirm}>
          🖨️ Drucken!
        </button>
      </div>
    </div>
  );
}

function DoneScreen({ state, dispatch }) {
  useEffect(() => {
    const id = setTimeout(() => dispatch({ type: "RESET" }), 20000);
    return () => clearTimeout(id);
  }, [dispatch]);
  const confetti = useMemo(() => Array.from({ length: 50 }, (_, i) => ({
    left: Math.random() * 100, delay: Math.random() * 2.5, dur: 2.5 + Math.random() * 2,
    color: STEP_COLORS.concat("#EC407A")[i % 6],
  })), []);
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, position: "relative", overflow: "hidden" }}>
      {confetti.map((c, i) => (
        <span key={i} style={{ position: "absolute", top: -20, left: `${c.left}%`, width: 12, height: 18, borderRadius: 3, background: c.color, animation: `fall ${c.dur}s linear ${c.delay}s infinite` }} />
      ))}
      <h1 style={{ fontSize: 30 }}>🎉 Super!</h1>
      <div style={{ fontSize: 130, fontWeight: 700, lineHeight: 1, color: "#2e9e44" }}>{state.job?.position ?? "?"}</div>
      <p style={{ fontSize: 22 }}>Du bist Nummer {state.job?.position}!</p>
      <p style={{ fontSize: 22 }}>Fertig ungefähr um {state.job?.eta}.</p>
      <p style={{ fontSize: 17, color: "#55555f" }}>Merk dir deine Nummer und sag sie am Stand!</p>
      <button style={btn("#2e9e44", "#fff")} onClick={() => dispatch({ type: "RESET" })}>Fertig</button>
    </div>
  );
}

/* ---------- Kiosk-Bildschirm (feste Design-Größe wie später am Pi) ---------- */
const STAGE_W = 1280;
const STAGE_H = 800;

function KioskScreen() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const step = state.screen >= 1 && state.screen <= 5 ? state.screen : 0;
  const accent = step >= 1 ? STEP_COLORS[step - 1] : "#1E88E5";
  return (
    <div style={{ "--accent": accent, width: STAGE_W, height: STAGE_H, display: "flex", flexDirection: "column", padding: "14px 16px", gap: 6, fontFamily: "'Trebuchet MS', system-ui, sans-serif", color: "#1c1c28", background: "#fff", userSelect: "none", overflow: "hidden", boxSizing: "border-box" }}>
      <style>{`
        @keyframes sway { 0%,100% { transform: rotate(-6deg); } 50% { transform: rotate(6deg); } }
        @keyframes pulse { 0%,100% { transform: scale(1); } 50% { transform: scale(1.06); } }
        @keyframes blink { 50% { opacity: 0; } }
        @keyframes shake { 0%,100% { transform: translateX(0); } 25% { transform: translateX(-10px); } 75% { transform: translateX(10px); } }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fall { to { transform: translateY(110vh) rotate(540deg); } }
        button:active { filter: brightness(.88); }
      `}</style>
      {step >= 1 && <Dots step={step} />}
      {state.screen === 0 && <Attract onStart={() => dispatch({ type: "START" })} />}
      {state.screen === 1 && <NameScreen state={state} dispatch={dispatch} />}
      {state.screen === 2 && <FontScreen state={state} dispatch={dispatch} />}
      {state.screen === 3 && <ShapeScreen state={state} dispatch={dispatch} />}
      {state.screen === 4 && <ColorScreen state={state} dispatch={dispatch} />}
      {state.screen === 5 && <PreviewScreen state={state} dispatch={dispatch} />}
      {state.screen === 6 && <DoneScreen state={state} dispatch={dispatch} />}
      {state.screen >= 1 && state.screen <= 4 && (
        <Nav onBack={state.screen > 1 ? () => dispatch({ type: "BACK" }) : undefined} onNext={() => dispatch({ type: "NEXT" })} disabled={!canGoNext(state)} />
      )}
    </div>
  );
}

/* ---------- Skalierungs-Hülle: passt den Kiosk-Bildschirm (1280x800)
   auf jede Fenstergröße (Handy hochkant, Tablet, Desktop) herunter,
   damit im Vorschau-Fenster immer alles sichtbar ist. ---------- */
function useViewportSize() {
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight });
  useEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", onResize);
    window.addEventListener("orientationchange", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("orientationchange", onResize);
    };
  }, []);
  return size;
}

export default function App() {
  const { w, h } = useViewportSize();
  const scale = Math.min(w / STAGE_W, h / STAGE_H, 1);
  return (
    <div style={{
      width: "100vw", height: "100vh", background: "#20202a",
      display: "flex", alignItems: "center", justifyContent: "center",
      overflow: "hidden",
    }}>
      <div style={{
        width: STAGE_W, height: STAGE_H,
        transform: `scale(${scale})`, transformOrigin: "center center",
        boxShadow: "0 0 0 1px rgba(255,255,255,.08), 0 20px 60px rgba(0,0,0,.5)",
        flexShrink: 0,
      }}>
        <KioskScreen />
      </div>
    </div>
  );
}
