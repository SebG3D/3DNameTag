import { useEffect, useRef, useState, type ReactNode } from "react";
import { STEPS, type Screen } from "../state";

export const STEP_COLORS = ["#EC407A", "#E53935", "#FB8C00", "#F9A825", "#43A047", "#1E88E5"];

export function Dots({ screen }: { screen: Screen }) {
  const step = STEPS.indexOf(screen);
  return (
    <div className="dots">
      {STEP_COLORS.map((c, i) => (
        <span key={i} className={i === step ? "dot cur" : "dot"}
          style={{ background: i <= step ? c : undefined, opacity: i < step ? 0.55 : 1 }} />
      ))}
    </div>
  );
}

export function Nav({ onBack, onNext, nextDisabled, nextLabel = "Weiter →", middle }: {
  onBack?: () => void;
  onNext?: () => void;
  nextDisabled?: boolean;
  nextLabel?: ReactNode;
  middle?: ReactNode;
}) {
  return (
    <div className="nav">
      {onBack ? <button className="btn btn-back" onClick={onBack}>← Zurück</button> : <span />}
      {middle ?? <span />}
      {onNext ? <button className="btn btn-go" disabled={nextDisabled} onClick={onNext}>{nextLabel}</button> : <span />}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="spinner-wrap">
      <div className="spinner" />
      {label}
    </div>
  );
}

/** "Bist du noch da?" after idleMs without touch, reset after another countdownS. */
export function IdleGuard({ active, idleMs = 90000, countdownS = 15, onTimeout }: {
  active: boolean;
  idleMs?: number;
  countdownS?: number;
  onTimeout: () => void;
}) {
  const [left, setLeft] = useState<number | null>(null);
  const last = useRef(Date.now());
  const cb = useRef(onTimeout);
  cb.current = onTimeout;

  useEffect(() => {
    if (!active) { setLeft(null); return; }
    last.current = Date.now();
    const touch = () => { last.current = Date.now(); };
    window.addEventListener("pointerdown", touch, true);
    const id = setInterval(() => {
      const idle = Date.now() - last.current;
      if (idle < idleMs) { setLeft(null); return; }
      const l = countdownS - Math.floor((idle - idleMs) / 1000);
      if (l <= 0) { setLeft(null); cb.current(); } else setLeft(l);
    }, 250);
    return () => { clearInterval(id); window.removeEventListener("pointerdown", touch, true); };
  }, [active, idleMs, countdownS]);

  if (left === null) return null;
  return (
    <div className="overlay">
      <div className="dialog">
        <h1>Bist du noch da?</h1>
        <p className="big-num">{left}</p>
        <button className="btn btn-go">Ja, weiter!</button>
      </div>
    </div>
  );
}

/** 5 taps in the top-left corner within 3 s → staff page (has its own PIN). */
export function StaffCorner() {
  const taps = useRef<number[]>([]);
  return (
    <div className="staff-corner" onPointerDown={() => {
      const now = Date.now();
      taps.current = [...taps.current.filter((t) => now - t < 3000), now];
      if (taps.current.length >= 5) window.location.href = "/staff/";
    }} />
  );
}
