import { Component, useEffect, useReducer, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { api, ApiError, type Config, type Status } from "./api";
import { ConfigContext, loadFonts } from "./config";
import { preloadIcons } from "./icons";
import { canGoNext, initialState, previewKey, reducer, STEPS } from "./state";
import { Dots, IdleGuard, Nav, StaffCorner, STEP_COLORS } from "./components/Chrome";
import { Attract } from "./screens/Attract";
import { ColorScreen, FontScreen, NameScreen, ShapeScreen } from "./screens/Wizard";
import { DoneScreen, OfflineScreen, ReviewScreen } from "./screens/Review";

// Design size; the stage is scaled to the real screen (1280x800, 1920x1080, ...).
const STAGE_W = 1280, STAGE_H = 800;

function useStageScale() {
  const get = () => Math.min(window.innerWidth / STAGE_W, window.innerHeight / STAGE_H);
  const [s, set] = useState(get);
  useEffect(() => {
    const on = () => set(get());
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return s;
}

function useStatus(enabled: boolean) {
  const [status, setStatus] = useState<Status | null>(null);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    let fails = 0, live = true, timer = 0;
    const poll = async () => {
      try {
        const s = await api.status();
        if (!live) return;
        fails = 0;
        setStatus(s);
        setOffline(false);
      } catch {
        if (live && ++fails >= 2) setOffline(true);
      }
      if (live) timer = window.setTimeout(poll, fails ? 5000 : 2000);
    };
    void poll();
    return () => { live = false; clearTimeout(timer); };
  }, [enabled]);
  return { status, offline };
}

function Kiosk() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const { status, offline } = useStatus(true);
  const s = state.screen;
  const step = STEPS.indexOf(s);
  const accent = step >= 0 ? STEP_COLORS[step] : "#1E88E5";

  // Render the real preview as soon as name, font and shape are known
  // (the colour screen shows it, the colour does not change the geometry).
  const key = previewKey(state.draft);
  const wanted = (s === "color" || s === "review") && key && key !== state.draft.previewKey;
  const inflight = useRef<string | null>(null);
  useEffect(() => {
    if (!wanted || !key || inflight.current === key) return;
    inflight.current = key;
    const [name, font, shape] = key.split("|");
    dispatch({ type: "PREVIEW_START", key });
    api.preview(name, font, shape)
      .then((p) => dispatch({ type: "PREVIEW_OK", key, preview: p }))
      .catch((e) => dispatch({ type: "PREVIEW_FAIL", key, code: e instanceof ApiError ? e.code : "x" }))
      .finally(() => { if (inflight.current === key) inflight.current = null; });
  }, [wanted, key]);

  return (
    <div className="stage" style={{ "--accent": accent } as CSSProperties}>
      <StaffCorner />
      {step >= 0 && <Dots screen={s} />}
      {s === "attract" && <Attract status={status} onStart={() => dispatch({ type: "START" })} />}
      {s === "name" && <NameScreen state={state} dispatch={dispatch} />}
      {s === "font" && <FontScreen state={state} dispatch={dispatch} />}
      {s === "shape" && <ShapeScreen state={state} dispatch={dispatch} />}
      {s === "color" && <ColorScreen state={state} dispatch={dispatch} />}
      {s === "review" && <ReviewScreen state={state} dispatch={dispatch} />}
      {s === "done" && <DoneScreen state={state} dispatch={dispatch} />}
      {step >= 0 && step < STEPS.length - 1 && (
        <Nav
          onBack={() => dispatch(step > 0 ? { type: "BACK" } : state.cart.length ? { type: "UNDO_ADD" } : { type: "RESET" })}
          onNext={() => dispatch({ type: "NEXT" })}
          nextDisabled={!canGoNext(state) || (s === "color" && !state.draft.preview)}
        />
      )}
      <IdleGuard active={s !== "attract" && s !== "done"} onTimeout={() => dispatch({ type: "RESET" })} />
      {offline && <div className="overlay solid"><OfflineScreen /></div>}
    </div>
  );
}

class ErrorBoundary extends Component<{ children: ReactNode }, { crashed: boolean }> {
  state = { crashed: false };
  static getDerivedStateFromError() { return { crashed: true }; }
  componentDidCatch(e: unknown) {
    console.error(e);
    setTimeout(() => window.location.reload(), 5000);
  }
  render() {
    return this.state.crashed ? <div className="stage"><div className="screen center"><h1>Hoppla!</h1><p className="sub">Ich starte gleich neu …</p></div></div> : this.props.children;
  }
}

export default function App() {
  const scale = useStageScale();
  const [cfg, setCfg] = useState<Config | null>(null);
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const c = await api.config();
        await loadFonts(c);
        if (!live) return;
        setCfg(c);
        void preloadIcons(c.shapes.map((s) => s.id));
      } catch {
        if (live) setTimeout(load, 5000);
      }
    };
    void load();
    return () => { live = false; };
  }, []);

  return (
    <div className="viewport">
      <div className="stage-scale" style={{ width: STAGE_W, height: STAGE_H, transform: `scale(${scale})` }}>
        <ErrorBoundary>
          {cfg ? (
            <ConfigContext.Provider value={cfg}><Kiosk /></ConfigContext.Provider>
          ) : (
            <div className="stage"><OfflineScreen /></div>
          )}
        </ErrorBoundary>
      </div>
    </div>
  );
}
